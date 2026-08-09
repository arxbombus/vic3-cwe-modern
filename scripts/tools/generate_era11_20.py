#!/usr/bin/env python3
"""Generate the CWE Era 11-20 technology extension from the current CWE source.

Design intent lives in the CSV manifests beside this script. The generator reads
current CWE definitions to select only production methods actually present in
active PMGs, to reuse Era-10 technology art/scaffolding, and to preserve current
unit/ship scaffolding. It deliberately never revives deprecated PMGs or dangling
PM definitions.

Usage:
    python tools/generate_era11_20.py --source /path/to/current/cwe --output /path/to/output

The era-cost policy is the project-approved Modern CWE curve:
round(5000 * era^1.20, nearest 500), with the approved explicit values below.
Era 1-10 are emitted as REPLACE definitions and Era 11-20 as new definitions.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import re
import shutil
import sys
from collections import defaultdict, Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ERA_COSTS = {
    1: 5000, 2: 11500, 3: 18500, 4: 26500, 5: 34500,
    6: 43000, 7: 51500, 8: 60500, 9: 70000, 10: 79000,
    11: 89000, 12: 98500, 13: 108500, 14: 118500, 15: 129000,
    16: 139500, 17: 150000, 18: 160500, 19: 171000, 20: 182000,
}
ERA_START = {era: 1900 + (era - 1) * 20 for era in range(1, 21)}

LOWER_STRATA = {"clerks", "farmers", "shopkeepers", "machinists", "laborers"}
MIDDLE_OR_HIGH_OR_SPECIAL = {
    "academics", "bureaucrats", "clergymen", "officers", "engineers",
    "peasants", "slaves", "soldiers", "capitalists", "aristocrats",
}
KNOWN_FORBIDDEN_GENERATED_PATTERNS = [
    r"pm_city_civil_defence_",
    r"pm_ground_forces_",
    r"pm_ground_forces_draft_",
    r"pm_airforce_",
    r"pm_airforce_draft_",
    r"pm_navy_doctrine_",
    r"pm_battleship_",
    r"pm_submarine_",
    r"pm_carrier_",
    r"pm_automation_\d+_building_agriculture",
    r"pm_technique_\d+_building_agriculture",
    r"pm_automation_\d+_building_mining",
    r"pm_technique_\d+_building_mining",
    r"pm_steel_goods_manufacturing_3\b",
    r"pm_advanced_artillery_goods_manufacturing\b",
    r"pm_advanced_tanks_goods_manufacturing\b",
    r"pm_advanced_warplanes_goods_manufacturing\b",
]

# PMGs whose mature CWE definitions do not provide a safe three-generation
# throughput progression. For these, future Goods PMs use an explicit arithmetic
# throughput rule: each new generation adds exactly 50% of the final live PM's
# positive goods inputs and outputs. This is an ABSOLUTE step, not compound scaling.
# The result is baseline + N * delta, so input and output increases are linear.
EXPLICIT_HALF_STEP_MARKET_PMGS = {
    'pmg_advanced_weaponry_manufacturing', 'pmg_aeroplanes_manufacturing',
    'pmg_ammunition_manufacturing', 'pmg_artillery_manufacturing',
    'pmg_automobiles_manufacturing', 'pmg_circuit_boards_manufacturing',
    'pmg_clothes_manufacturing', 'pmg_computers_manufacturing',
    'pmg_consumer_robots_manufacturing', 'pmg_corporate_services_services',
    'pmg_engines_manufacturing', 'pmg_financial_services_regulation_services',
    'pmg_financial_services_services', 'pmg_fine_art_manufacturing',
    'pmg_furniture_manufacturing', 'pmg_groceries_manufacturing',
    'pmg_industrial_robots_manufacturing', 'pmg_liquor_manufacturing',
    'pmg_locomotives_manufacturing', 'pmg_media_services_services',
    'pmg_oil_power_infrastructure', 'pmg_pharmaceuticals_manufacturing',
    'pmg_plastics_manufacturing', 'pmg_professional_services_services',
    'pmg_recreational_services_intoxicants', 'pmg_recreational_services_services',
    'pmg_recreational_services_tourism_services', 'pmg_retail_services_services',
    'pmg_rubber_manufacturing', 'pmg_small_arms_manufacturing',
    'pmg_software_services', 'pmg_tanks_manufacturing',
    'pmg_telecommunications_manufacturing', 'pmg_warplanes_manufacturing',
}

# Sparse families where the existing CWE cadence is clear enough to encode as a
# family-specific absolute delta instead of the 50%-of-baseline fallback. Keys are
# (modifier subblock, modifier key). Inputs omitted here are held at the live value.
EXPLICIT_MARKET_GOODS_DELTAS = {
    'pmg_steel_manufacturing': {('workforce_scaled', 'goods_output_steel_add'): 50},
    'pmg_hydroelectric_power_infrastructure': {('workforce_scaled', 'goods_output_electricity_add'): 200},
    'pmg_geothermal_power_infrastructure': {('workforce_scaled', 'goods_output_electricity_add'): 200},
}

# Keys that were introduced during the last three live PMs and therefore are not
# present in all three reference generations. Their continuation is explicit.
LINEAR_GOODS_DELTA_OVERRIDES = {
    'pmg_rail_design_infrastructure': {('workforce_scaled', 'goods_input_electricity_add'): 10},
    'pmg_bureaucracy_government': {('workforce_scaled', 'goods_input_software_add'): 1},
}

EXPLICIT_NONMARKET_GOODS_PMGS = {
    # These PMGs are input-substitution/design choices rather than a mature
    # throughput sequence, so their future material package follows the
    # project-approved explicit rule instead of extrapolating a misleading slope.
    'pmg_base_building_construction_sector',
    'pmg_skyscraper_energy_source',
}

# Chains for which future direct modifiers should be re-read from the live
# Era-10 technology, rather than trusting the snapshot in the manifest.
COPY_ERA10_MODIFIER_CHAINS = {
    "tech_air_infrastructure",
    "tech_economy",
    "tech_geopolitics",
    "tech_land_infrastructure",
    "tech_military_navy_doctrine",
    "tech_philosophy",
}

# ---------------------------------------------------------------------------
# Clausewitz/Jomini light parser
# ---------------------------------------------------------------------------
@dataclass
class Atom:
    value: str

@dataclass
class Pair:
    key: str
    value: "Value"

@dataclass
class Block:
    items: list[Union[Atom, Pair]]

Value = Union[Atom, Block]

TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[{}=]|[^\s{}=]+')


def strip_comments(text: str) -> str:
    out = []
    in_quote = False
    escape = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_quote = False
            i += 1
            continue
        if ch == '"':
            in_quote = True
            out.append(ch)
            i += 1
            continue
        if ch == '#':
            while i < len(text) and text[i] != '\n':
                i += 1
            if i < len(text):
                out.append('\n')
                i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def tokenize(text: str) -> list[str]:
    text = text.lstrip('\ufeff')
    return TOKEN_RE.findall(strip_comments(text))


def parse_tokens(tokens: list[str]) -> Block:
    i = 0

    def parse_value() -> Value:
        nonlocal i
        if i >= len(tokens):
            raise ValueError("Unexpected EOF")
        if tokens[i] == '{':
            i += 1
            items: list[Union[Atom, Pair]] = []
            while i < len(tokens) and tokens[i] != '}':
                tok = tokens[i]
                if i + 1 < len(tokens) and tokens[i + 1] == '=':
                    key = tok
                    i += 2
                    val = parse_value()
                    items.append(Pair(key, val))
                else:
                    items.append(Atom(tok))
                    i += 1
            if i >= len(tokens) or tokens[i] != '}':
                raise ValueError("Unclosed block")
            i += 1
            return Block(items)
        tok = tokens[i]
        i += 1
        return Atom(tok)

    root_items: list[Union[Atom, Pair]] = []
    while i < len(tokens):
        tok = tokens[i]
        if i + 1 < len(tokens) and tokens[i + 1] == '=':
            key = tok
            i += 2
            root_items.append(Pair(key, parse_value()))
        else:
            root_items.append(Atom(tok))
            i += 1
    return Block(root_items)


def parse_file(path: Path) -> Block:
    return parse_tokens(tokenize(path.read_text(encoding='utf-8-sig', errors='replace')))


def block_pairs(block: Block, key: Optional[str] = None) -> list[Pair]:
    return [x for x in block.items if isinstance(x, Pair) and (key is None or x.key == key)]


def block_atoms(block: Block) -> list[str]:
    return [x.value for x in block.items if isinstance(x, Atom)]


def get_pair(block: Block, key: str) -> Optional[Pair]:
    ps = block_pairs(block, key)
    return ps[-1] if ps else None


def get_block(block: Block, key: str, create: bool = False) -> Optional[Block]:
    p = get_pair(block, key)
    if p and isinstance(p.value, Block):
        return p.value
    if create:
        b = Block([])
        set_pair(block, key, b)
        return b
    return None


def get_atom(block: Block, key: str) -> Optional[str]:
    p = get_pair(block, key)
    if p and isinstance(p.value, Atom):
        return p.value.value
    return None


def set_pair(block: Block, key: str, value: Union[str, float, int, Block]) -> None:
    if not isinstance(value, (Atom, Block)):
        value = Atom(format_number(value) if isinstance(value, (int, float)) else str(value))
    block.items = [x for x in block.items if not (isinstance(x, Pair) and x.key == key)]
    block.items.append(Pair(key, value))


def prepend_pair(block: Block, key: str, value: Union[str, Block]) -> None:
    if not isinstance(value, (Atom, Block)):
        value = Atom(str(value))
    block.items = [x for x in block.items if not (isinstance(x, Pair) and x.key == key)]
    block.items.insert(0, Pair(key, value))


def remove_key(block: Block, key: str) -> None:
    block.items = [x for x in block.items if not (isinstance(x, Pair) and x.key == key)]


def atom_block(values: Iterable[str]) -> Block:
    return Block([Atom(str(v)) for v in values])


def as_number(atom: Optional[str]) -> Optional[float]:
    if atom is None:
        return None
    v = atom.strip('"')
    try:
        return float(v)
    except ValueError:
        return None


def format_number(v: Union[int, float]) -> str:
    if isinstance(v, int):
        return str(v)
    if abs(v - round(v)) < 1e-10:
        return str(int(round(v)))
    s = f"{v:.6f}".rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def quote(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def serialize_value(value: Value, indent: int = 0) -> str:
    if isinstance(value, Atom):
        return value.value
    return serialize_block(value, indent)


def serialize_block(block: Block, indent: int = 0) -> str:
    pad = '\t' * indent
    inner = '\t' * (indent + 1)
    # Small atom-only lists are readable inline.
    if block.items and all(isinstance(x, Atom) for x in block.items) and len(block.items) <= 8:
        return '{ ' + ' '.join(x.value for x in block.items if isinstance(x, Atom)) + ' }'
    lines = ['{']
    for item in block.items:
        if isinstance(item, Atom):
            lines.append(f"{inner}{item.value}")
        else:
            if isinstance(item.value, Atom):
                lines.append(f"{inner}{item.key} = {item.value.value}")
            else:
                nested = serialize_block(item.value, indent + 1)
                first, *rest = nested.splitlines()
                lines.append(f"{inner}{item.key} = {first}")
                lines.extend(rest)
    lines.append(f"{pad}}}")
    return '\n'.join(lines)


def serialize_definition(def_id: str, block: Block) -> str:
    body = serialize_block(block, 0)
    return f"{def_id} = {body}\n"


def load_definitions(directory: Path) -> tuple[dict[str, Block], dict[str, Path]]:
    defs: dict[str, Block] = {}
    files: dict[str, Path] = {}
    if not directory.exists():
        return defs, files
    for path in sorted(directory.rglob('*.txt')):
        try:
            root = parse_file(path)
        except Exception as e:
            raise RuntimeError(f"Failed parsing {path}: {e}") from e
        for item in root.items:
            if isinstance(item, Pair) and isinstance(item.value, Block):
                defs[item.key] = item.value
                files[item.key] = path
    return defs, files

# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------
def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def parse_semicolon_map(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    if not text.strip():
        return out
    for part in text.split(';'):
        part = part.strip()
        if not part:
            continue
        k, v = part.split('=', 1)
        out[k.strip()] = float(v.strip())
    return out


def trailing_int(identifier: str) -> int:
    m = re.search(r'_(\d+)$', identifier)
    if not m:
        return 1
    return int(m.group(1))


def roman(n: int) -> str:
    vals = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]
    out=''
    for value, sym in vals:
        while n >= value:
            out += sym
            n -= value
    return out

# ---------------------------------------------------------------------------
# Tree manipulation helpers
# ---------------------------------------------------------------------------
def numeric_pairs(block: Block) -> Iterable[Pair]:
    for item in block.items:
        if isinstance(item, Pair):
            if isinstance(item.value, Atom) and as_number(item.value.value) is not None:
                yield item


def add_numeric(block: Block, key: str, delta: float) -> None:
    cur = as_number(get_atom(block, key)) or 0.0
    set_pair(block, key, cur + delta)


def scale_positive_numeric(block: Block, prefixes: tuple[str, ...], factor: float, exclude_prefixes: tuple[str, ...] = ()) -> None:
    for item in list(numeric_pairs(block)):
        if item.key.startswith(exclude_prefixes):
            continue
        if item.key.startswith(prefixes):
            v = as_number(item.value.value)
            if v is not None and v > 0:
                item.value = Atom(format_number(v * factor))


def scale_positive_recursive(block: Block, factor: float, exclude_prefixes: tuple[str, ...] = ()) -> None:
    for item in block.items:
        if isinstance(item, Pair):
            if isinstance(item.value, Atom):
                v = as_number(item.value.value)
                if v is not None and v > 0 and not item.key.startswith(exclude_prefixes):
                    item.value = Atom(format_number(v * factor))
            elif isinstance(item.value, Block):
                scale_positive_recursive(item.value, factor, exclude_prefixes)


def ensure_mod_subblock(pm: Block, outer: str, inner: str) -> Block:
    out = get_block(pm, outer, create=True)
    assert out is not None
    inn = get_block(out, inner, create=True)
    assert inn is not None
    return inn


def remove_mod_key(pm: Block, outer: str, inner: str, key: str) -> None:
    out = get_block(pm, outer)
    if not out:
        return
    inn = get_block(out, inner)
    if not inn:
        return
    remove_key(inn, key)
    if not inn.items:
        remove_key(out, inner)


def employment_entries(pm: Block) -> tuple[Optional[Block], dict[str, float]]:
    bm = get_block(pm, 'building_modifiers')
    if not bm:
        return None, {}
    lv = get_block(bm, 'level_scaled')
    if not lv:
        return None, {}
    vals: dict[str, float] = {}
    for p in numeric_pairs(lv):
        m = re.fullmatch(r'building_employment_([a-z_]+)_add', p.key)
        if m:
            vals[m.group(1)] = as_number(p.value.value) or 0.0
    return lv, vals


def apply_employment_transition(pm: Block, fraction: float, force_all_lower: bool = False, output_if_unchanged_middle: bool = True) -> str:
    """Change lower-strata employment into engineers without applying output bonuses.

    Output bonuses are deliberately handled by Generator.apply_specific_output_bonus(),
    because a generic goods_output_mult is unsafe for compatibility and meaningless
    for buildings such as Universities and Construction Sectors.
    """
    lv, entries = employment_entries(pm)
    if not lv or not entries:
        return 'no-employment'
    fraction = 1.0 if force_all_lower else max(0.0, min(1.0, fraction))
    converted_total = 0.0
    for pop, value in list(entries.items()):
        if pop in LOWER_STRATA and value > 0:
            convert = value * fraction
            converted_total += convert
            set_pair(lv, f'building_employment_{pop}_add', value - convert)
    if converted_total > 0:
        eng = as_number(get_atom(lv, 'building_employment_engineers_add')) or 0.0
        set_pair(lv, 'building_employment_engineers_add', eng + converted_total)
        lv.items = [x for x in lv.items if not (isinstance(x, Pair) and isinstance(x.value, Atom) and x.key.startswith('building_employment_') and (as_number(x.value.value) or 0.0) == 0)]
        return 'converted'
    return 'unchanged'


def set_texture(pm: Block, texture_path: str) -> None:
    # Keep texture first for readability.
    prepend_pair(pm, 'texture', quote(texture_path))


def set_unlock_tech(pm: Block, tech_id: str) -> None:
    set_pair(pm, 'unlocking_technologies', atom_block([tech_id]))

# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
class Generator:
    def __init__(self, source: Path, output: Path, manifests: Path):
        self.source = source
        self.output = output
        self.manifests = manifests
        self.tech_rows = read_csv(manifests / '01_technologies.csv')
        self.pm_rows = read_csv(manifests / '02_production_methods.csv')
        self.unit_rows = read_csv(manifests / '03_combat_units.csv')
        self.ship_rows = read_csv(manifests / '04_ships.csv')
        self.mob_rows = read_csv(manifests / '05_mobilization_options.csv')
        self.coverage_rows = read_csv(manifests / '06_active_goods_pmg_coverage.csv')
        self.fix_rows = read_csv(manifests / '07_era_1_10_fixes.csv')

        self.tech_defs, self.tech_files = load_definitions(source / 'common/technology/technologies')
        self.pm_defs, self.pm_files = load_definitions(source / 'common/production_methods')
        self.pmg_defs, self.pmg_files = load_definitions(source / 'common/production_method_groups')
        self.building_defs, self.building_files = load_definitions(source / 'common/buildings')
        self.unit_defs, self.unit_files = load_definitions(source / 'common/combat_unit_types')
        self.ship_defs, self.ship_files = load_definitions(source / 'common/ship_types')
        self.mob_defs, self.mob_files = load_definitions(source / 'common/mobilization_options')

        self.active_pmgs = self.discover_active_pmgs()
        self.pmg_methods = {pmg: self.get_pmg_methods(pmg) for pmg in self.pmg_defs}
        self.baseline_pm = {pmg: self.get_baseline_pm_id(pmg) for pmg in self.pmg_defs}
        self.active_goods_pmgs = {row['pmg'] for row in self.coverage_rows}
        self.pmg_host_buildings = self.discover_pmg_host_buildings()
        self.building_output_goods = {bid: self.building_market_output_goods(bid) for bid in self.building_defs}
        self.market_goods_pmgs = {pmg for pmg in self.active_pmgs if any(self.pm_has_market_output(pid) for pid in self.pmg_methods.get(pmg, []) if pid in self.pm_defs)}
        self.generated_pm_blocks: dict[str, Block] = {}
        self.generated_tech_blocks: dict[str, Block] = {}
        self.generated_unit_blocks: dict[str, Block] = {}
        self.generated_ship_blocks: dict[str, Block] = {}
        self.generated_mob_blocks: dict[str, Block] = {}
        self.validation: dict[str, object] = {}

        self.pm_rows_by_pmg: dict[str, list[dict[str,str]]] = defaultdict(list)
        for row in self.pm_rows:
            self.pm_rows_by_pmg[row['pmg']].append(row)

    # ------------------------- source discovery -------------------------
    def discover_active_pmgs(self) -> set[str]:
        active: set[str] = set()
        for bid, b in self.building_defs.items():
            pg = get_block(b, 'production_method_groups')
            if pg:
                active.update(block_atoms(pg))
        return active

    def get_pmg_methods(self, pmg: str) -> list[str]:
        b = self.pmg_defs.get(pmg)
        if not b:
            return []
        pb = get_block(b, 'production_methods')
        return block_atoms(pb) if pb else []

    def get_baseline_pm_id(self, pmg: str) -> Optional[str]:
        methods = self.get_pmg_methods(pmg)
        usable = [p for p in methods if p in self.pm_defs]
        return usable[-1] if usable else None

    # ------------------------- paths / graphics -------------------------
    def pm_icon_path(self, row: dict[str,str]) -> str:
        kind = row['pm_kind']
        label = {
            'Goods': 'good',
            'Organisation': 'organization',
            'Automation': 'automation',
            'Technique': 'technique',
            'Urban Special': 'technique',
            'Nuclear Type': 'technique',
            'Nuclear Rocket': 'technique',
        }.get(kind, 'technique')
        # Sea Infrastructure's live port-operating slot is historically classified
        # under the broad Goods PMG family, but these specific future PMs are
        # explicitly Technique generations in the approved design/localization.
        if row.get('stat_rule') == 'SEA-PORT' or 'building_port_technique' in row['pm_id']:
            label = 'technique'
        pid = row['pm_id']
        # Employment-series PM IDs place the technological tier in the middle
        # (e.g. pm_modern_automation_11_building_services), while Goods/special
        # PMs conventionally place it at the end.
        m = re.search(r'pm_modern_(?:automation|organisation|technique)_(\d+)_', pid)
        tier = int(m.group(1)) if m else trailing_int(pid)
        return f"gfx/interface/icons/production_method_icons/modern_future/{label}_{roman(tier).lower()}.png"

    def unit_icon_path(self, unit_id: str) -> str:
        tier = trailing_int(unit_id)
        if 'airforce' in unit_id:
            cls = 'air'
        elif 'artillery' in unit_id:
            cls = 'artillery'
        else:
            cls = 'infantry'
        return f"gfx/unit_illustrations/modern_future/{cls}_{roman(tier).lower()}.png"

    # ------------------------- technologies -------------------------
    def source_tech_template(self, chain: str, era: int = 10) -> Block:
        tid = f"{chain}_{era}"
        if tid not in self.tech_defs:
            raise RuntimeError(f"Missing source technology {tid}")
        return self.tech_defs[tid]

    def resolve_tech_modifiers(self, row: dict[str,str]) -> dict[str,float]:
        chain = row['chain']
        era = int(row['era'])
        if chain in COPY_ERA10_MODIFIER_CHAINS:
            src = self.source_tech_template(chain, 10)
            mod = get_block(src, 'modifier')
            out: dict[str,float] = {}
            if mod:
                for p in numeric_pairs(mod):
                    out[p.key] = as_number(p.value.value) or 0.0
            return out
        if chain == 'tech_politics':
            # Preserve the source's alternating cadence (Era 9 package on odd,
            # Era 10 package on even), so upstream value changes are inherited.
            src_era = 10 if era % 2 == 0 else 9
            src = self.source_tech_template(chain, src_era)
            mod = get_block(src, 'modifier')
            out: dict[str,float] = {}
            if mod:
                for p in numeric_pairs(mod):
                    out[p.key] = as_number(p.value.value) or 0.0
            return out
        if chain == 'tech_military_theory':
            src = self.source_tech_template(chain, 10)
            mod = get_block(src, 'modifier')
            out: dict[str,float] = {}
            if mod:
                for p in numeric_pairs(mod):
                    if p.key in ('unit_morale_loss_mult', 'unit_morale_loss_add'):
                        continue
                    out[p.key] = as_number(p.value.value) or 0.0
            out['unit_morale_recovery_mult'] = 0.05
            return out
        return parse_semicolon_map(row['direct_modifiers'])

    def generate_technologies(self) -> None:
        for row in self.tech_rows:
            chain = row['chain']
            era = int(row['era'])
            tmpl = self.source_tech_template(chain, 10)
            texture = get_atom(tmpl, 'texture')
            category = get_atom(tmpl, 'category') or row['category']
            ai = copy.deepcopy(get_block(tmpl, 'ai_weight') or Block([Pair('value', Atom('1'))]))
            b = Block([])
            set_pair(b, 'era', f'era_{era}')
            if texture:
                set_pair(b, 'texture', texture)
            set_pair(b, 'category', category)
            prereqs = [row['prerequisite']]
            if era == 11:
                src_unlock = get_block(tmpl, 'unlocking_technologies')
                if src_unlock:
                    for extra in block_atoms(src_unlock):
                        if extra != f'{chain}_9' and extra not in prereqs:
                            prereqs.append(extra)
            set_pair(b, 'unlocking_technologies', atom_block(prereqs))
            mods = self.resolve_tech_modifiers(row)
            if mods:
                mb = Block([])
                for k,v in mods.items():
                    set_pair(mb, k, v)
                set_pair(b, 'modifier', mb)
            set_pair(b, 'ai_weight', ai)
            self.generated_tech_blocks[row['tech_id']] = b

    def write_technology_files(self) -> None:
        cat_map = {'production':'10_production_era11_20.txt','military':'20_military_era11_20.txt','society':'30_society_era11_20.txt'}
        grouped: dict[str,list[dict[str,str]]] = defaultdict(list)
        for row in self.tech_rows: grouped[row['category']].append(row)
        outdir = self.output / 'common/technology/technologies'
        outdir.mkdir(parents=True, exist_ok=True)
        for cat, rows in grouped.items():
            lines = [f"# Generated CWE Era 11-20 {cat} technologies\n"]
            for row in rows:
                lines.append(f"# Era {row['era']}: {row['localized_name']}\n")
                lines.append(serialize_definition(row['tech_id'], self.generated_tech_blocks[row['tech_id']]))
                lines.append('\n')
            (outdir / cat_map[cat]).write_text(''.join(lines), encoding='utf-8')

    def write_eras(self) -> None:
        outdir = self.output / 'common/technology/eras'
        outdir.mkdir(parents=True, exist_ok=True)
        lines = [
            '### Modern CWE technology eras\n',
            '### Cost curve: round(5000 * era^1.20, nearest 500)\n\n',
        ]
        for era in range(1, 21):
            start = ERA_START[era]
            end = start + 19
            prefix = 'REPLACE:' if era <= 10 else ''
            lines += [
                f"{prefix}era_{era} = {{ #{start}-{end}\n",
                f"\tstart_date = {start}.01.01\n",
                f"\tend_date = {end}.12.31\n",
                f"\ttechnology_cost = {ERA_COSTS[era]}\n",
                "}\n\n",
            ]
        (outdir / 'z_modern_eras_1_20.txt').write_text(''.join(lines), encoding='utf-8')

    def write_old_tech_fixes(self) -> None:
        outdir = self.output / 'common/technology/technologies'
        outdir.mkdir(parents=True, exist_ok=True)
        lines = ['# Static compatibility-only fixes for zero-effect CWE Era 1-10 technologies.\n# Modifier-only by design: no unlocks are injected here.\n\n']
        for row in self.fix_rows:
            mods = parse_semicolon_map(row['modifier'])
            lines.append(f"INJECT:{row['tech_id']} = {{\n\tmodifier = {{\n")
            for k,v in mods.items():
                lines.append(f"\t\t{k} = {format_number(v)}\n")
            lines.append("\t}\n}\n\n")
        (outdir / 'z_modern_era1_10_compatibility_fixes.txt').write_text(''.join(lines), encoding='utf-8')

    # ------------------------- PM generation -------------------------
    def baseline_pm_block(self, pmg: str) -> Block:
        if pmg not in self.active_pmgs:
            raise RuntimeError(f"Manifest targets inactive PMG {pmg}")
        pid = self.baseline_pm.get(pmg)
        if not pid or pid not in self.pm_defs:
            raise RuntimeError(f"No active+defined baseline PM for {pmg}")
        return copy.deepcopy(self.pm_defs[pid])

    def pm_ordinal(self, row: dict[str,str]) -> tuple[int,int]:
        rows = self.pm_rows_by_pmg[row['pmg']]
        idx = next(i for i,x in enumerate(rows) if x['pm_id'] == row['pm_id'])
        return idx + 1, len(rows)

    def partial_factor(self, row: dict[str,str]) -> float:
        idx, n = self.pm_ordinal(row)
        return 1.0 + idx / n

    def add_workforce_delta(self, pm: Block, deltas: dict[str,float], step: float = 1.0) -> None:
        wf = ensure_mod_subblock(pm, 'building_modifiers', 'workforce_scaled')
        for key, d in deltas.items():
            add_numeric(wf, key, d * step)

    def add_state_pollution(self, pm: Block, delta: float) -> None:
        wf = ensure_mod_subblock(pm, 'state_modifiers', 'workforce_scaled')
        add_numeric(wf, 'state_pollution_generation_add', delta)

    def apply_ag_rule(self, pm: Block, rule: str, era: int) -> None:
        step = era - 10
        common = {
            'goods_input_industrial_chemicals_add': 1,
            'goods_input_oil_add': 1,
            'goods_input_industrial_robots_add': 0.5,
            'goods_input_software_add': 0.5,
        }
        output_key_map = {
            'AG-GRAIN':'goods_output_grain_add','AG-FABRIC':'goods_output_fabric_add','AG-FRUIT':'goods_output_fruit_add',
            'AG-RUBBER':'goods_output_rubber_add','AG-COFFEE':'goods_output_coffee_add','AG-TEA':'goods_output_tea_add',
            'AG-TOBACCO':'goods_output_tobacco_add','AG-WINE':'goods_output_wine_add','AG-OPIUM':'goods_output_opium_add',
        }
        if rule == 'AG-FISH':
            d = {'goods_input_industrial_chemicals_add':1,'goods_input_industrial_robots_add':1,'goods_input_oil_add':1,'goods_input_software_add':0.5,'goods_input_steamers_add':0.5,'goods_output_fish_add':100}
        elif rule == 'AG-MEAT':
            d = {'goods_input_electricity_add':1,'goods_input_grain_add':10,'goods_input_industrial_chemicals_add':1,'goods_input_industrial_robots_add':0.5,'goods_input_software_add':0.5,'goods_input_fabric_add':10,'goods_output_meat_add':100}
        else:
            d = dict(common)
            if rule in ('AG-WINE','AG-OPIUM'):
                d['goods_input_industrial_chemicals_add'] = 2
                output = 50
            elif rule in ('AG-COFFEE','AG-TEA','AG-TOBACCO'):
                output = 50
            else:
                output = 100
            d[output_key_map[rule]] = output
        self.add_workforce_delta(pm, d, step)

    def apply_mine_rule(self, pm: Block, rule: str, era: int) -> None:
        step = era - 10
        res = rule.replace('MINE-','').lower()
        if rule == 'MINE-COAL':
            d = {'goods_input_electricity_add':2,'goods_input_industrial_robots_add':2,'goods_input_software_add':0.5,'goods_output_coal_add':50}
        elif rule == 'MINE-OIL':
            d = {'goods_input_industrial_robots_add':0.5,'goods_input_software_add':0.5,'goods_output_oil_add':25}
        else:
            out = 100 if rule == 'MINE-IRON' else 50
            d = {'goods_input_electricity_add':2,'goods_input_industrial_robots_add':2,'goods_input_oil_add':2,'goods_input_software_add':0.5,f'goods_output_{res}_add':out}
            if rule == 'MINE-LEAD': d['goods_output_gold_add'] = 1
        self.add_workforce_delta(pm, d, step)
        self.add_state_pollution(pm, step * 1)

    def apply_log_rule(self, pm: Block, era: int) -> None:
        step = era - 10
        self.add_workforce_delta(pm, {'goods_input_industrial_robots_add':1,'goods_input_oil_add':1,'goods_input_software_add':0.5,'goods_output_wood_add':200}, step)
        self.add_state_pollution(pm, step)

    def apply_auto_service(self, pm: Block, row: dict[str,str]) -> None:
        step = int(row['era']) - 10
        self.add_workforce_delta(pm, {'goods_input_communication_add':0.5,'goods_input_electricity_add':1,'goods_input_software_add':1,'goods_input_computers_add':0.5}, step)
        self.add_state_pollution(pm, step)
        if row['stat_rule'] == 'AUTO-SERVICE-MIDDLE':
            apply_employment_transition(pm, 0, output_if_unchanged_middle=True)
        else:
            apply_employment_transition(pm, step/10)

    def apply_auto_manufacturing(self, pm: Block, row: dict[str,str]) -> None:
        step = int(row['era']) - 10
        d = {'goods_input_communication_services_add':0.5,'goods_input_electricity_add':0.5,'goods_input_software_add':0.5}
        if 'machinery' in row['pm_id']:
            d['goods_input_engines_add'] = 0.5
        else:
            d['goods_input_industrial_robots_add'] = 0.5
        self.add_workforce_delta(pm, d, step)
        self.add_state_pollution(pm, 2*step)
        apply_employment_transition(pm, step/10)

    def apply_org_land(self, pm: Block, row: dict[str,str]) -> None:
        step = int(row['era']) - 10
        d = {'goods_input_corporate_services_add':0.5}
        if 'manufacturing' in row['pm_id']:
            d['goods_input_transportation_add'] = 0.5
        else:
            d['goods_input_transportation_add'] = 1
        self.add_workforce_delta(pm, d, step)
        apply_employment_transition(pm, step/10)

    def apply_org_service(self, pm: Block, row: dict[str,str]) -> None:
        step = int(row['era']) - 10
        if row['stat_rule'] == 'ORG-SERVICE-MIDDLE':
            apply_employment_transition(pm, 0, output_if_unchanged_middle=True)
        else:
            apply_employment_transition(pm, step/10)

    def apply_comm_net(self, pm: Block, row: dict[str,str]) -> None:
        step = int(row['era']) - 10
        self.add_workforce_delta(pm, {'goods_input_professional_services_add':0.2,'goods_output_communication_services_add':25}, step)
        self.add_state_pollution(pm, step)
        apply_employment_transition(pm, step/10)

    def apply_university_technique(self, pm: Block, row: dict[str,str]) -> None:
        step = int(row['era']) - 10
        self.add_workforce_delta(pm, {'goods_input_communication_services_add':1,'goods_input_electricity_add':1,'goods_input_software_add':1}, step)
        # CWE's live University Technique series expresses innovation through
        # country_weekly_innovation_add in country_modifiers.workforce_scaled.
        # Continue that exact live key rather than inventing a new modifier.
        cw = ensure_mod_subblock(pm, 'country_modifiers', 'workforce_scaled')
        base_innovation = as_number(get_atom(cw, 'country_weekly_innovation_add')) or 0.0
        set_pair(cw, 'country_weekly_innovation_add', base_innovation + step)
        apply_employment_transition(pm, step/10)

    def apply_partial_goods(self, pm: Block, row: dict[str,str], force_factor: Optional[float]=None) -> None:
        factor = force_factor if force_factor is not None else self.partial_factor(row)
        bm = get_block(pm, 'building_modifiers')
        if bm:
            for subname in ('workforce_scaled','level_scaled','unscaled'):
                sub = get_block(bm, subname)
                if sub:
                    scale_positive_numeric(sub, ('goods_input_','goods_output_'), factor)
        apply_employment_transition(pm, (int(row['era'])-10)/10)

    def apply_university_base(self, pm: Block, row: dict[str,str]) -> None:
        """Extend the University's base education PM by its real outputs.

        Universities do not produce ordinary market goods. Their live base PM
        produces innovation and qualifications, so future generations continue
        those outputs while preserving academic employment.
        """
        idx, _ = self.pm_ordinal(row)
        wf = ensure_mod_subblock(pm, 'building_modifiers', 'workforce_scaled')
        # Continue the live +1 furniture-input cadence without inventing a goods output.
        set_pair(wf, 'goods_input_furniture_add', 3 + idx)
        lv = ensure_mod_subblock(pm, 'building_modifiers', 'level_scaled')
        # Preserve the current all-middle-strata academic workforce.
        lv.items = [x for x in lv.items if not (isinstance(x, Pair) and x.key.startswith('building_employment_'))]
        set_pair(lv, 'building_employment_academics_add', 3000)
        cw = ensure_mod_subblock(pm, 'country_modifiers', 'workforce_scaled')
        set_pair(cw, 'country_weekly_innovation_add', 6 + 2 * idx)
        sw = ensure_mod_subblock(pm, 'state_modifiers', 'workforce_scaled')
        set_pair(sw, 'state_pop_qualifications_mult', 0.3 + 0.1 * idx)
        remove_mod_key(pm, 'building_modifiers', 'unscaled', 'goods_output_mult')

    def apply_essential_services(self, pm: Block, row: dict[str,str]) -> None:
        """Continue public-service capacity, not nonexistent goods output."""
        idx, _ = self.pm_ordinal(row)
        su = ensure_mod_subblock(pm, 'state_modifiers', 'unscaled')
        set_pair(su, 'state_pop_qualifications_mult', 0.05 + 0.02 * idx)
        set_pair(su, 'state_infrastructure_add', 50 + 20 * idx)
        wf = ensure_mod_subblock(pm, 'building_modifiers', 'workforce_scaled')
        wf.items = [x for x in wf.items if not (isinstance(x, Pair) and x.key.startswith('goods_input_'))]
        set_pair(wf, 'goods_input_pharmaceuticals_add', 3 + idx)
        set_pair(wf, 'goods_input_furniture_add', 3 + idx)
        lv = ensure_mod_subblock(pm, 'building_modifiers', 'level_scaled')
        lv.items = [x for x in lv.items if not (isinstance(x, Pair) and x.key.startswith('building_employment_'))]
        set_pair(lv, 'building_employment_engineers_add', 2000)
        set_pair(lv, 'building_employment_academics_add', 2000)
        remove_mod_key(pm, 'building_modifiers', 'unscaled', 'goods_output_mult')

    def apply_security_services(self, pm: Block, row: dict[str,str]) -> None:
        """Continue policing effectiveness while retaining special soldier staffing."""
        idx, _ = self.pm_ordinal(row)
        wf = ensure_mod_subblock(pm, 'building_modifiers', 'workforce_scaled')
        wf.items = [x for x in wf.items if not (isinstance(x, Pair) and x.key.startswith('goods_input_'))]
        set_pair(wf, 'goods_input_ammunition_add', 4 + idx)
        set_pair(wf, 'goods_input_small_arms_add', 2 + 0.5 * idx)
        lv = ensure_mod_subblock(pm, 'building_modifiers', 'level_scaled')
        lv.items = [x for x in lv.items if not (isinstance(x, Pair) and x.key.startswith('building_employment_'))]
        set_pair(lv, 'building_employment_soldiers_add', 2000)
        su = ensure_mod_subblock(pm, 'state_modifiers', 'unscaled')
        set_pair(su, 'state_turmoil_effects_mult', -0.20 - 0.05 * idx)
        remove_mod_key(pm, 'building_modifiers', 'unscaled', 'goods_output_mult')

    def apply_forex(self, pm: Block, row: dict[str,str]) -> None:
        """Give advanced fiat/clearing systems an actual monetary output."""
        idx, _ = self.pm_ordinal(row)
        cw = ensure_mod_subblock(pm, 'country_modifiers', 'workforce_scaled')
        # Fiat starts at zero minting in the live PMG. Future monetary networks
        # progressively recover seigniorage/clearing efficiency without touching laws.
        set_pair(cw, 'country_minting_add', 100 * idx)

    def apply_energy(self, pm: Block, row: dict[str,str]) -> None:
        if row['pmg'] == 'pmg_skyscraper_energy_source':
            idx, _ = self.pm_ordinal(row)
            wf = ensure_mod_subblock(pm, 'building_modifiers', 'workforce_scaled')
            # A more capable megastructure grid consumes more electrical power but
            # raises the output of the skyscraper's real-estate Goods PMG.
            wf.items = [x for x in wf.items if not (isinstance(x, Pair) and x.key.startswith('goods_input_'))]
            set_pair(wf, 'goods_input_electricity_add', 50 * (1 + 0.25 * idx))
            un = ensure_mod_subblock(pm, 'building_modifiers', 'unscaled')
            set_pair(un, 'goods_output_mult', 0.1 * idx)
            sw = ensure_mod_subblock(pm, 'state_modifiers', 'workforce_scaled')
            set_pair(sw, 'state_pollution_generation_add', max(0.0, 1.0 - 0.25 * idx))
            return
        self.apply_partial_goods(pm, row)
        apply_employment_transition(pm, 1.0, force_all_lower=True)

    def apply_construction_goods(self, pm: Block, row: dict[str,str]) -> None:
        idx, _ = self.pm_ordinal(row)
        factor = 1 + 0.2 * idx
        bm = get_block(pm, 'building_modifiers')
        if bm:
            # CWE's final construction PM stores its material package in
            # level_scaled. Continue that exact basket with an absolute +20% of
            # the live endpoint per new generation (1.2x, 1.4x, ... 2.0x).
            for subname in ('workforce_scaled', 'level_scaled', 'unscaled'):
                sub = get_block(bm, subname)
                if sub:
                    scale_positive_numeric(sub, ('goods_input_',), factor)
            # explicit construction values per plan
            country = get_block(pm, 'country_modifiers', create=True)
            if country:
                w = get_block(country, 'workforce_scaled', create=True)
                if w:
                    set_pair(w, 'country_construction_add', 6 + idx)
            state = get_block(pm, 'state_modifiers', create=True)
            if state:
                w = get_block(state, 'workforce_scaled', create=True)
                if w:
                    set_pair(w, 'state_construction_mult', 0.03 + 0.01*idx)
        apply_employment_transition(pm, idx/5)

    def apply_construction_size(self, pm: Block, row: dict[str,str]) -> None:
        idx, _ = self.pm_ordinal(row)
        # Construction sectors do not output market goods. Rebuild the live
        # level-scaled labor/input package and reward the professionalized workforce
        # with construction output instead of an inert goods_output_mult.
        bm = get_block(pm, 'building_modifiers', create=True)
        assert bm is not None
        bm.items = []
        lv = Block([])
        set_pair(lv, 'goods_input_transportation_add', 12 + 2 * idx)
        set_pair(lv, 'goods_input_communication_services_add', 10 + 2 * idx)
        set_pair(lv, 'goods_input_industrial_robots_add', 5 + idx)
        set_pair(lv, 'goods_input_computers_add', 3 + idx)
        set_pair(lv, 'goods_input_software_add', 6 + 2 * idx)
        laborers = max(0, 500 - 100 * idx)
        engineers = min(500, 100 * idx)
        if laborers:
            set_pair(lv, 'building_employment_laborers_add', laborers)
        if engineers:
            set_pair(lv, 'building_employment_engineers_add', engineers)
        set_pair(bm, 'level_scaled', lv)
        cw = ensure_mod_subblock(pm, 'country_modifiers', 'workforce_scaled')
        # pm_construction_5 provides 6 construction; +0.6 is the intended 10%
        # productivity premium for paying the upgraded workforce higher wages.
        set_pair(cw, 'country_construction_add', 0.6)

    def apply_transport_design(self, pm: Block, row: dict[str,str]) -> None:
        idx, _ = self.pm_ordinal(row)
        factor = 1.0 + 0.25 * idx
        for outer_name in ('building_modifiers','state_modifiers'):
            outer = get_block(pm, outer_name)
            if outer:
                # Scale positive operating inputs/outputs and infrastructure/transport effects, never employment.
                for subname in ('workforce_scaled','level_scaled','unscaled'):
                    sub = get_block(outer, subname)
                    if sub:
                        for item in list(numeric_pairs(sub)):
                            if item.key.startswith('building_employment_'):
                                continue
                            if item.key.startswith(('goods_input_','goods_output_')) or 'infrastructure' in item.key or 'transport' in item.key or 'trade_capacity' in item.key:
                                v = as_number(item.value.value)
                                if v is not None and v > 0:
                                    item.value = Atom(format_number(v * factor))
        apply_employment_transition(pm, (int(row['era'])-10)/10)

    def apply_air_design(self, pm: Block, row: dict[str,str]) -> None:
        idx, _ = self.pm_ordinal(row)
        self.add_workforce_delta(pm, {
            'goods_input_aeroplanes_add':1,
            'goods_input_oil_add':10,
            'goods_output_transportation_add':50,
            'goods_output_merchant_marine_add':5,
        }, idx)
        # Infrastructure/trade capacity live outside goods block in some source PMs.
        for outer, key, delta in [('state_modifiers','state_infrastructure_add',10),('state_modifiers','state_trade_capacity_add',1)]:
            wf = ensure_mod_subblock(pm,outer,'workforce_scaled'); add_numeric(wf,key,delta*idx)
        apply_employment_transition(pm,(int(row['era'])-10)/10)

    def apply_sea_port(self, pm: Block, row: dict[str,str]) -> None:
        idx, _ = self.pm_ordinal(row)
        # Keep current mechanics, explicitly convert the 1000 laborers in 50/100% steps.
        lv, entries = employment_entries(pm)
        if lv:
            # normalize lower-strata total into laborers+engineers per user's port rule
            lower_total = sum(v for p,v in entries.items() if p in LOWER_STRATA)
            for p in list(entries):
                if p in LOWER_STRATA: remove_key(lv, f'building_employment_{p}_add')
            eng_existing = entries.get('engineers',0)
            target_eng = eng_existing + lower_total * (0.5 if idx==1 else 1.0)
            remaining = lower_total * (0.5 if idx==1 else 0.0)
            if remaining: set_pair(lv,'building_employment_laborers_add',remaining)
            set_pair(lv,'building_employment_engineers_add',target_eng)
            un=ensure_mod_subblock(pm,'building_modifiers','unscaled');set_pair(un,'goods_output_mult',0.1)

    def apply_sea_scaled(self, pm: Block, row: dict[str,str]) -> None:
        idx, _ = self.pm_ordinal(row)
        factor = 1.5 if idx == 1 else 2.0
        bm = get_block(pm,'building_modifiers')
        if bm:
            for subname in ('workforce_scaled','level_scaled'):
                sub=get_block(bm,subname)
                if sub: scale_positive_numeric(sub,('goods_input_','goods_output_'),factor)
        apply_employment_transition(pm,0.5 if idx==1 else 1.0)

    def apply_bureaucracy(self, pm: Block, row: dict[str,str]) -> None:
        idx, _ = self.pm_ordinal(row)
        # The live cadence is +100 Bureaucracy and (from the mature tiers) +100
        # Tax Capacity per generation. Government Administration has no market-goods
        # output, so goods_output_mult would be mechanically meaningless here.
        cl = ensure_mod_subblock(pm, 'country_modifiers', 'level_scaled')
        set_pair(cl, 'country_bureaucracy_add', 500 + 100 * idx)
        sl = ensure_mod_subblock(pm, 'state_modifiers', 'level_scaled')
        set_pair(sl, 'state_tax_capacity_add', 500 + 100 * idx)
        wf = ensure_mod_subblock(pm, 'building_modifiers', 'workforce_scaled')
        wf.items = [x for x in wf.items if not (isinstance(x, Pair) and x.key.startswith('goods_input_'))]
        set_pair(wf, 'goods_input_furniture_add', 4 + idx)
        set_pair(wf, 'goods_input_communication_services_add', 4 + idx)
        set_pair(wf, 'goods_input_software_add', 2 + idx)
        set_pair(wf, 'goods_input_transportation_add', 4 + idx)
        set_pair(wf, 'goods_input_electricity_add', 4 + idx)
        lv = ensure_mod_subblock(pm, 'building_modifiers', 'level_scaled')
        lv.items = [x for x in lv.items if not (isinstance(x, Pair) and x.key.startswith('building_employment_'))]
        set_pair(lv, 'building_employment_bureaucrats_add', 5000)
        remove_mod_key(pm, 'building_modifiers', 'unscaled', 'goods_output_mult')

    def apply_urban_goods(self, pm: Block, row: dict[str,str]) -> None:
        idx,_=self.pm_ordinal(row)
        factor=1+0.2*idx
        bm=get_block(pm,'building_modifiers')
        if bm:
            for subname in ('workforce_scaled','level_scaled','unscaled'):
                sub=get_block(bm,subname)
                if sub: scale_positive_numeric(sub,('goods_input_','goods_output_'),factor)
        apply_employment_transition(pm,idx/5)

    def apply_urban_special(self, pm: Block, row: dict[str,str]) -> None:
        idx,_=self.pm_ordinal(row)
        factor=1+0.2*idx
        # Scale positive operational effects, but never employment counts.
        for outer_name in ('building_modifiers','state_modifiers','country_modifiers'):
            outer=get_block(pm,outer_name)
            if outer: scale_positive_recursive(outer,factor,exclude_prefixes=('building_employment_',))
        if row['pmg'] in ('pmg_city_utilities_urban_center','pmg_city_transport_urban_center'):
            apply_employment_transition(pm,idx/5)

    def generate_nuclear_type(self, row: dict[str,str]) -> Block:
        base = copy.deepcopy(self.pm_defs['pm_nuclear_type_2'])
        tier=trailing_int(row['pm_id'])
        set_texture(base,self.pm_icon_path(row)); set_unlock_tech(base,row['tech_id'])
        # Preserve WMD law and timed modifier scaffolding, replace operational stats.
        wf=ensure_mod_subblock(base,'building_modifiers','workforce_scaled')
        # remove existing goods inputs, then set planned input
        wf.items=[x for x in wf.items if not (isinstance(x,Pair) and x.key.startswith('goods_input_'))]
        set_pair(wf,'goods_input_industrial_chemicals_add',10*tier)
        lv=ensure_mod_subblock(base,'building_modifiers','level_scaled')
        lv.items=[x for x in lv.items if not (isinstance(x,Pair) and x.key.startswith('building_employment_'))]
        set_pair(lv,'building_employment_engineers_add',2000)
        set_pair(lv,'building_employment_soldiers_add',200)
        cw=ensure_mod_subblock(base,'country_modifiers','workforce_scaled')
        # source uses project/projection typo risk; use live key if present, else valid inventory key
        key='country_prestige_from_army_power_projection_mult'
        for p in numeric_pairs(cw):
            if 'prestige_from_army_power' in p.key: key=p.key
        set_pair(cw,key,0.01*tier)
        return base

    def generate_nuclear_rocket(self, row: dict[str,str]) -> Block:
        base=copy.deepcopy(self.pm_defs['pm_nuclear_rocket_1'])
        tier=trailing_int(row['pm_id'])
        idx=tier-2
        set_texture(base,self.pm_icon_path(row));set_unlock_tech(base,row['tech_id'])
        wf=ensure_mod_subblock(base,'building_modifiers','workforce_scaled')
        wf.items=[x for x in wf.items if not (isinstance(x,Pair) and x.key.startswith('goods_input_'))]
        set_pair(wf,'goods_input_advanced_weaponry_add',8+3*idx)
        set_pair(wf,'goods_input_oil_add',30+5*idx)
        lv=ensure_mod_subblock(base,'building_modifiers','level_scaled')
        lv.items=[x for x in lv.items if not (isinstance(x,Pair) and x.key.startswith('building_employment_'))]
        set_pair(lv,'building_employment_officers_add',100)
        cw=ensure_mod_subblock(base,'country_modifiers','workforce_scaled')
        key='country_prestige_from_army_power_projection_mult'
        for p in numeric_pairs(cw):
            if 'prestige_from_army_power' in p.key:key=p.key
        set_pair(cw,key,0.03+0.02*idx)
        req=['pm_nuclear_type_1','pm_nuclear_type_2']+[f'pm_modern_nuclear_type_{n}' for n in range(3,tier+2)]
        set_pair(base,'unlocking_production_methods',atom_block(req))
        return base

    # ------------------------- V3 PM progression helpers -------------------------
    def normalize_duplicate_blocks(self, block: Block) -> None:
        """Merge duplicate block-valued keys recursively.

        CWE occasionally repeats blocks such as level_scaled inside one modifier.
        The game accepts this pattern, but a generator must see all entries when
        deriving progression. Numeric duplicates inside a merged block remain in
        source order; setters below collapse the specific keys they update.
        """
        i = 0
        while i < len(block.items):
            item = block.items[i]
            if isinstance(item, Pair) and isinstance(item.value, Block):
                same = [x for x in block.items if isinstance(x, Pair) and x.key == item.key and isinstance(x.value, Block)]
                if len(same) > 1:
                    merged = Block([])
                    for x in same:
                        merged.items.extend(copy.deepcopy(x.value.items))
                    block.items = [x for x in block.items if not (isinstance(x, Pair) and x.key == item.key and isinstance(x.value, Block))]
                    block.items.insert(i, Pair(item.key, merged))
                    item = block.items[i]
                self.normalize_duplicate_blocks(item.value)
            i += 1

    def goods_profile_from_block(self, source: Block) -> dict[tuple[str,str], float]:
        """Return direct building goods input/output adds from a PM block.

        Per-good multipliers are intentionally excluded: this profile is the
        arithmetic input/output package used for linear-progression validation.
        """
        pm = copy.deepcopy(source)
        self.normalize_duplicate_blocks(pm)
        out: dict[tuple[str,str], float] = {}
        bm = get_block(pm, 'building_modifiers')
        if not bm:
            return out
        for subname in ('workforce_scaled', 'level_scaled', 'unscaled'):
            sub = get_block(bm, subname)
            if not sub:
                continue
            for pair in numeric_pairs(sub):
                if pair.key.startswith(('goods_input_', 'goods_output_')) and pair.key.endswith('_add'):
                    out[(subname, pair.key)] = as_number(pair.value.value) or 0.0
        return out

    def source_goods_profile(self, pm_id: str) -> dict[tuple[str,str], float]:
        """Return direct source PM goods inputs/outputs, merging duplicate blocks."""
        if pm_id not in self.pm_defs:
            return {}
        return self.goods_profile_from_block(self.pm_defs[pm_id])

    def pm_has_market_output(self, pm_id: str) -> bool:
        return any(k.startswith('goods_output_') and v > 0 for (_, k), v in self.source_goods_profile(pm_id).items())

    def source_market_pm_ids(self, pmg: str) -> list[str]:
        ids = [pid for pid in self.pmg_methods.get(pmg, []) if pid in self.pm_defs]
        return [pid for pid in ids if self.pm_has_market_output(pid)]

    def linear_market_goods_deltas(self, pmg: str) -> tuple[dict[tuple[str,str], float], str, list[str]]:
        """Choose the absolute per-generation goods delta for a market Goods PMG.

        Mature families use the last THREE productive live PMs (never a no-output
        base method) and extrapolate the arithmetic slope (third-first)/2.
        Families that are sparse, flat-output, or input-substitution choices are
        explicitly enumerated above and use fixed family rules instead.
        """
        market_ids = self.source_market_pm_ids(pmg)
        if not market_ids:
            raise RuntimeError(f'{pmg} has no live market-output PM to extend')
        latest = market_ids[-1]
        latest_profile = self.source_goods_profile(latest)

        if pmg in EXPLICIT_MARKET_GOODS_DELTAS:
            return dict(EXPLICIT_MARKET_GOODS_DELTAS[pmg]), 'explicit-family', market_ids[-3:]

        if pmg in EXPLICIT_HALF_STEP_MARKET_PMGS:
            deltas = {path: value * 0.5 for path, value in latest_profile.items() if value > 0}
            # Every explicit throughput family must actually gain output.
            if not any(key.startswith('goods_output_') and delta > 0 for (_, key), delta in deltas.items()):
                raise RuntimeError(f'Explicit throughput rule for {pmg} has no positive output delta')
            return deltas, 'explicit-half-baseline', market_ids[-3:]

        if len(market_ids) < 3:
            raise RuntimeError(f'{pmg} needs an explicit linear rule: only {len(market_ids)} productive live PMs')
        refs = market_ids[-3:]
        profiles = [self.source_goods_profile(pid) for pid in refs]
        common = set(profiles[0]) & set(profiles[1]) & set(profiles[2])
        deltas: dict[tuple[str,str], float] = {}
        for path in common:
            v1, _, v3 = profiles[0][path], profiles[1][path], profiles[2][path]
            deltas[path] = (v3 - v1) / 2.0

        # A mature throughput family is only auto-extrapolated when its output is
        # genuinely increasing and none of its continuing inputs is declining.
        output_paths = [p for p in common if p[1].startswith('goods_output_')]
        if not output_paths or any(deltas[p] <= 0 for p in output_paths):
            raise RuntimeError(f'{pmg} has flat/non-positive mature output and must be explicitly configured')
        if any(deltas[p] < 0 for p in common if p[1].startswith('goods_input_')):
            raise RuntimeError(f'{pmg} has declining mature inputs and must be explicitly configured')

        for path, delta in LINEAR_GOODS_DELTA_OVERRIDES.get(pmg, {}).items():
            deltas[path] = delta
        return deltas, 'last-three-live', refs

    def recent_three_direct_goods_deltas(self, pmg: str) -> tuple[dict[tuple[str,str],float], list[str]] | None:
        """Derive direct-goods deltas from the latest three live PMs.

        This is used for Automation, Organisation, University, Government and
        other non-Goods slots whose *inputs* still progress numerically. Missing
        keys in one of the three PMs count as zero, allowing a newly introduced
        input such as bureaucracy software to continue naturally. PMGs that are
        really substitution/design choices are explicitly excluded above.
        """
        if pmg in EXPLICIT_NONMARKET_GOODS_PMGS:
            return None
        ids = [pid for pid in self.pmg_methods.get(pmg, []) if pid in self.pm_defs]
        if len(ids) < 3:
            return None
        refs = ids[-3:]
        profiles = [self.source_goods_profile(pid) for pid in refs]
        paths = set().union(*(set(profile) for profile in profiles))
        if not paths:
            return None
        deltas: dict[tuple[str,str],float] = {}
        for path in paths:
            vals = [profile.get(path, 0.0) for profile in profiles]
            delta = (vals[2] - vals[0]) / 2.0
            # A declining material trend represents substitution/efficiency rather
            # than the requested future throughput progression; leave such PMGs to
            # an explicit family rule instead of extrapolating negative inputs.
            if delta < -1e-9:
                return None
            deltas[path] = delta
        for path, delta in LINEAR_GOODS_DELTA_OVERRIDES.get(pmg, {}).items():
            deltas[path] = delta
        return deltas, refs

    def apply_recent_three_direct_goods_progression(self, pm: Block, row: dict[str,str]) -> bool:
        resolved = self.recent_three_direct_goods_deltas(row['pmg'])
        if not resolved:
            return False
        deltas, refs = resolved
        latest = self.source_goods_profile(refs[-1])
        if not latest and not deltas:
            return False
        ordinal, _ = self.pm_ordinal(row)
        bm = get_block(pm, 'building_modifiers', create=True)
        assert bm is not None
        # Remove only direct goods adds; employment and domain-specific modifiers
        # produced by the family helper remain untouched.
        for subname in ('workforce_scaled', 'level_scaled', 'unscaled'):
            sub = get_block(bm, subname, create=True)
            assert sub is not None
            sub.items = [item for item in sub.items if not (
                isinstance(item, Pair) and item.key.startswith(('goods_input_', 'goods_output_')) and item.key.endswith('_add')
            )]
        paths = set(latest) | set(deltas)
        for path in sorted(paths):
            value = latest.get(path, 0.0) + deltas.get(path, 0.0) * ordinal
            if value <= 0:
                continue
            sub = get_block(bm, path[0], create=True); assert sub is not None
            set_pair(sub, path[1], value)
        return True

    def clear_generic_goods_output_mult(self, pm: Block) -> None:
        bm = get_block(pm, 'building_modifiers')
        if not bm:
            return
        for subname in ('workforce_scaled', 'level_scaled', 'unscaled'):
            sub = get_block(bm, subname)
            if sub:
                remove_key(sub, 'goods_output_mult')

    def apply_market_goods_progression(self, pm: Block, row: dict[str,str]) -> tuple[str,list[str],dict[tuple[str,str],float]]:
        pmg = row['pmg']
        market_ids = self.source_market_pm_ids(pmg)
        latest_id = market_ids[-1]
        latest = self.source_goods_profile(latest_id)
        deltas, mode, refs = self.linear_market_goods_deltas(pmg)
        ordinal, _ = self.pm_ordinal(row)

        # Start from the final productive live PM's goods package, not from a base
        # or choice PM. This prevents future PMs from ever regressing below the
        # mature live method.
        bm = get_block(pm, 'building_modifiers', create=True)
        assert bm is not None
        for subname in ('workforce_scaled', 'level_scaled', 'unscaled'):
            sub = get_block(bm, subname, create=True)
            assert sub is not None
            sub.items = [x for x in sub.items if not (isinstance(x, Pair) and x.key.startswith(('goods_input_', 'goods_output_')))]

        profile = dict(latest)
        for path, delta in deltas.items():
            base = latest.get(path, 0.0)
            value = base + delta * ordinal
            if value < -1e-9:
                raise RuntimeError(f'{row["pm_id"]}: linear progression drives {path} negative ({value})')
            profile[path] = max(0.0, value)
        for (subname, key), value in profile.items():
            if value <= 0:
                continue
            sub = get_block(bm, subname, create=True)
            assert sub is not None
            set_pair(sub, key, value)
        return mode, refs, deltas

    def discover_pmg_host_buildings(self) -> dict[str, list[str]]:
        hosts: dict[str, list[str]] = defaultdict(list)
        for bid, b in self.building_defs.items():
            pg = get_block(b, 'production_method_groups')
            if not pg:
                continue
            for pmg in block_atoms(pg):
                hosts[pmg].append(bid)
        return hosts

    def direct_market_output_goods_for_pmg(self, pmg: str) -> set[str]:
        """Return only the market goods directly produced by this PMG.

        This deliberately ignores outputs from unrelated PMGs on the same building
        (for example corruption producing illegal_services).  A per-good productivity
        modifier attached to an Automation/Organisation PM should improve the host
        building's *productive Goods slot*, not every side-effect output that happens
        to exist elsewhere on the building.
        """
        goods: set[str] = set()
        for pid in self.pmg_methods.get(pmg, []):
            if pid not in self.pm_defs:
                continue
            for (_, key), value in self.source_goods_profile(pid).items():
                m = re.fullmatch(r'goods_output_(.+)_add', key)
                if m and value > 0:
                    goods.add(m.group(1))
        return goods

    def building_market_output_goods(self, building_id: str) -> set[str]:
        """Return market goods from the building's active Goods PMGs only."""
        b = self.building_defs[building_id]
        pg = get_block(b, 'production_method_groups')
        goods: set[str] = set()
        if not pg:
            return goods
        for host_pmg in block_atoms(pg):
            if host_pmg not in self.active_goods_pmgs:
                continue
            goods.update(self.direct_market_output_goods_for_pmg(host_pmg))
        return goods

    def output_goods_for_pmg(self, pmg: str) -> list[str]:
        # If this is itself a productive Goods PMG, modifiers should target only
        # the goods it directly produces.  For Automation/Organisation/etc., use
        # the productive Goods slots of the buildings that actually host it.
        direct = self.direct_market_output_goods_for_pmg(pmg)
        if direct:
            return sorted(direct)
        goods: set[str] = set()
        for bid in self.pmg_host_buildings.get(pmg, []):
            goods.update(self.building_output_goods.get(bid, set()))
        return sorted(goods)

    def apply_specific_output_bonus(self, pm: Block, pmg: str, amount: float) -> bool:
        """Apply compatibility-safe per-good output multipliers to host outputs."""
        self.clear_generic_goods_output_mult(pm)
        goods = self.output_goods_for_pmg(pmg)
        if not goods or amount == 0:
            return False
        un = ensure_mod_subblock(pm, 'building_modifiers', 'unscaled')
        for good in goods:
            set_pair(un, f'goods_output_{good}_mult', amount)
        return True

    def progressive_output_bonus(self, row: dict[str,str], starting_bonus: float) -> float:
        """Return the approved arithmetic productivity bonus for a future PM series.

        A series that starts at +10% gains another +5 percentage points with each
        successive new PM: 10%, 15%, 20%, ... . A series that starts at +20% gains
        another +10 percentage points: 20%, 30%, 40%, ... . This is keyed to the
        PM's ordinal within its generated PMG continuation, not the calendar era, so
        sparse PM families still increase once per actual new PM level.
        """
        idx, _ = self.pm_ordinal(row)
        return starting_bonus * (1.0 + 0.5 * (idx - 1))

    def apply_employment_bonus(self, pm: Block, row: dict[str,str], fraction: float, *, force_all_lower: bool=False, unchanged_bonus: float=0.2, converted_bonus: float=0.1) -> str:
        status = apply_employment_transition(pm, fraction, force_all_lower=force_all_lower)
        if status == 'converted':
            self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, converted_bonus))
        elif status == 'unchanged':
            self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, unchanged_bonus))
        return status

    def apply_v3_market_side_effects(self, pm: Block, row: dict[str,str]) -> None:
        rule = row['stat_rule']
        era = int(row['era'])
        idx, _ = self.pm_ordinal(row)
        if rule.startswith('MINE-'):
            self.add_state_pollution(pm, era - 10)
        elif rule == 'LOG-WOOD':
            self.add_state_pollution(pm, era - 10)
        elif rule in ('PARTIAL-GOODS', 'PARTIAL-GOODS-10'):
            self.apply_employment_bonus(pm, row, (era - 10) / 10)
        elif rule in ('ENERGY-PARTIAL',):
            self.apply_employment_bonus(pm, row, 1.0, force_all_lower=True)
        elif rule == 'COMM-NET':
            self.add_state_pollution(pm, era - 10)
            self.apply_employment_bonus(pm, row, (era - 10) / 10)
        elif rule == 'TRANSPORT-DESIGN':
            self.apply_employment_bonus(pm, row, (era - 10) / 10)
        elif rule == 'AIR-DESIGN':
            # Continue non-goods airport capacity at the same simple absolute step.
            sw = ensure_mod_subblock(pm, 'state_modifiers', 'workforce_scaled')
            add_numeric(sw, 'state_infrastructure_add', 10 * idx)
            add_numeric(sw, 'state_trade_capacity_add', 1 * idx)
            self.apply_employment_bonus(pm, row, (era - 10) / 10)
        elif rule == 'SEA-PORT':
            # Exactly two generations: 50% then 100% of the live lower-strata port workforce.
            status = apply_employment_transition(pm, 0.5 if idx == 1 else 1.0)
            if status == 'converted':
                self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.1))
            elif status == 'unchanged':
                self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.2))
        elif rule in ('SEA-DESIGN', 'SEA-STEAMERS'):
            self.apply_employment_bonus(pm, row, 0.5 if idx == 1 else 1.0)
        elif rule == 'URBAN-GOODS':
            self.apply_employment_bonus(pm, row, idx / max(1, len(self.pm_rows_by_pmg[row['pmg']])))
        elif rule == 'URBAN-SPECIAL':
            # Utilities and transport are productive PMGs too; continue their direct
            # goods package arithmetically, then professionalize their workforce.
            # Real-estate intensity has no employment to convert, so this is a no-op
            # there beyond the direct last-three goods progression above.
            self.apply_employment_bonus(pm, row, idx / max(1, len(self.pm_rows_by_pmg[row['pmg']])))
        # Pure Goods PMs with no employment do not need a separate productivity bonus.

    def generate_pm(self, row: dict[str,str]) -> Block:
        rule = row['stat_rule']
        if rule == 'NUCLEAR-TYPE':
            pm = self.generate_nuclear_type(row)
            self.clear_generic_goods_output_mult(pm)
            return pm
        if rule == 'NUCLEAR-ROCKET':
            pm = self.generate_nuclear_rocket(row)
            self.clear_generic_goods_output_mult(pm)
            return pm

        pm = self.baseline_pm_block(row['pmg'])
        self.normalize_duplicate_blocks(pm)
        set_texture(pm, self.pm_icon_path(row))
        set_unlock_tech(pm, row['tech_id'])
        self.clear_generic_goods_output_mult(pm)
        era = int(row['era'])

        # Market-output Goods PMGs use the V3 arithmetic progression engine.
        if row['pmg'] in self.market_goods_pmgs:
            self.apply_market_goods_progression(pm, row)
            self.apply_v3_market_side_effects(pm, row)
            return pm

        # Non-market-output PMGs keep domain-specific mechanics.
        if row['pmg'] == 'pmg_base_building_university':
            self.apply_university_base(pm, row)
        elif row['pmg'] == 'pmg_essential_services_government':
            self.apply_essential_services(pm, row)
        elif row['pmg'] == 'pmg_security_services_government':
            self.apply_security_services(pm, row)
        elif row['pmg'] == 'pmg_forex_government':
            self.apply_forex(pm, row)
        elif rule in ('AUTO-SERVICE-CONVERT', 'AUTO-SERVICE-MIDDLE'):
            self.apply_auto_service(pm, row)
            self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.2 if rule == 'AUTO-SERVICE-MIDDLE' else 0.1))
        elif rule == 'AUTO-MANUFACTURING':
            self.apply_auto_manufacturing(pm, row)
            self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.1))
        elif rule == 'ORG-LAND':
            self.apply_org_land(pm, row)
            self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.1))
        elif rule in ('ORG-SERVICE-CONVERT', 'ORG-SERVICE-MIDDLE'):
            self.apply_org_service(pm, row)
            self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.2 if rule == 'ORG-SERVICE-MIDDLE' else 0.1))
        elif rule == 'UNIVERSITY-TECHNIQUE':
            self.apply_university_technique(pm, row)
        elif rule == 'CONSTRUCTION-GOODS':
            self.apply_construction_goods(pm, row)
        elif rule == 'CONSTRUCTION-SIZE':
            self.apply_construction_size(pm, row)
        elif rule == 'BUREAUCRACY-GOODS':
            self.apply_bureaucracy(pm, row)
        elif rule == 'URBAN-SPECIAL':
            self.apply_urban_special(pm, row)
            if row['pmg'] in ('pmg_city_utilities_urban_center', 'pmg_city_transport_urban_center'):
                self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.1))
        elif rule == 'ENERGY-PARTIAL' and row['pmg'] == 'pmg_skyscraper_energy_source':
            self.apply_energy(pm, row)
            self.clear_generic_goods_output_mult(pm)
            # The energy-source PM affects the skyscraper's real-estate output.
            idx, _ = self.pm_ordinal(row)
            self.apply_specific_output_bonus(pm, row['pmg'], self.progressive_output_bonus(row, 0.1))
        else:
            raise RuntimeError(f'Unhandled V3 PM stat rule {rule} for {row["pm_id"]}')

        # For non-market PM families with a genuine numeric goods-input history,
        # re-derive the material progression from the current source's latest
        # three PMs. This makes regeneration adapt automatically when CWE changes
        # its recent input cadence. Explicit substitution families are excluded.
        self.apply_recent_three_direct_goods_progression(pm, row)
        self.clear_generic_goods_output_mult(pm)
        return pm

    def generate_pms(self) -> None:
        for row in self.pm_rows:
            self.generated_pm_blocks[row['pm_id']] = self.generate_pm(row)

    def write_pm_files(self) -> None:
        outdir = self.output / 'common/production_methods'
        outdir.mkdir(parents=True, exist_ok=True)
        lines = [
            '# Generated CWE Era 11-20 production methods\n',
            '# All future PM definitions intentionally live in this single file.\n\n',
        ]
        # Keep manifest order so review follows the approved chain/PMG cadence.
        for row in self.pm_rows:
            lines.append(f"# {row['localized_name']} ({row['pmg']})\n")
            lines.append(serialize_definition(row['pm_id'], self.generated_pm_blocks[row['pm_id']]))
            lines.append('\n')
        (outdir / 'z_modern_era11_20_production_methods.txt').write_text(''.join(lines), encoding='utf-8')

    def write_pmg_injections(self) -> None:
        outdir=self.output/'common/production_method_groups';outdir.mkdir(parents=True,exist_ok=True)
        grouped=defaultdict(list)
        for row in self.pm_rows:grouped[row['pmg']].append(row['pm_id'])
        lines=['# Append generated Era 11-20 PMs to live CWE PMGs.\n# No unused/deprecated PMG is targeted.\n\n']
        for pmg in sorted(grouped):
            if pmg not in self.active_pmgs: raise RuntimeError(f"Refusing injection into inactive PMG {pmg}")
            lines.append(f"INJECT:{pmg} = {{\n\tproduction_methods = {{\n")
            for pid in grouped[pmg]:lines.append(f"\t\t{pid}\n")
            lines.append("\t}\n}\n\n")
        (outdir/'z_modern_era11_20_pmg_injections.txt').write_text(''.join(lines),encoding='utf-8')

    # ------------------------- combat units -------------------------
    def parse_unit_stats(self,text:str)->dict[str,float]: return parse_semicolon_map(text)

    def generate_unit(self,row:dict[str,str])->Block:
        uid=row['unit_id']; stats=self.parse_unit_stats(row['stats'])
        if 'airforce' in uid: baseid='combat_unit_type_airforce_10'
        elif 'artillery' in uid: baseid='combat_unit_type_artillery_10'
        else: baseid='combat_unit_type_infantry_10'
        if baseid not in self.unit_defs: raise RuntimeError(f"Missing {baseid}")
        base=copy.deepcopy(self.unit_defs[baseid])
        # core scalar fields
        set_pair(base,'group',row['group'])
        set_pair(base,'max_manpower',int(stats['max_manpower']))
        if get_atom(base,'conscript_peasant_levies') is None:set_pair(base,'conscript_peasant_levies','yes')
        set_pair(base,'supply_capacity',stats['supply_capacity'])
        up=get_block(base,'upkeep_modifier',create=True); assert up
        up.items=[]
        good_map={'warplanes':'warplanes','ammunition':'ammunition','advanced_weaponry':'advanced_weaponry','oil':'oil','small_arms':'small_arms','tanks':'tanks','communication_services':'communication_services','artillery':'artillery'}
        for sk,g in good_map.items():
            if sk in stats:set_pair(up,f'goods_input_{g}_add',stats[sk])
        battle=get_block(base,'battle_modifier',create=True);assert battle
        battle.items=[]
        stat_to_key={'offense':'unit_offense_add','defense':'unit_defense_add','morale_damage_mult':'unit_morale_damage_mult','morale_loss_add':'unit_morale_loss_add','morale_recovery_mult':'unit_morale_recovery_mult','provinces_captured_mult':'unit_provinces_captured_mult','kill_rate_add':'unit_kill_rate_add','devastation_mult':'unit_devastation_mult','naval_invasion_efficiency_mult':'unit_naval_invasion_efficiency_mult'}
        for sk,k in stat_to_key.items():
            if sk in stats:set_pair(battle,k,stats[sk])
        form=get_block(base,'formation_modifier',create=True)
        if any(k in stats for k in ('formation_mobilization_speed_mult','formation_movement_speed_mult')):
            if form is None:
                form=Block([]);set_pair(base,'formation_modifier',form)
            form.items=[]
            if 'formation_mobilization_speed_mult' in stats:set_pair(form,'military_formation_mobilization_speed_mult',stats['formation_mobilization_speed_mult'])
            if 'formation_movement_speed_mult' in stats:set_pair(form,'military_formation_movement_speed_mult',stats['formation_movement_speed_mult'])
        set_pair(base,'unlocking_technologies',atom_block([row['tech_id']]))
        # Replace all culture art with one deterministic future card.
        base.items=[x for x in base.items if not (isinstance(x,Pair) and x.key=='combat_unit_image')]
        base.items.append(Pair('combat_unit_image',Block([Pair('texture',Atom(quote(self.unit_icon_path(uid))))])))
        # CWE combat-unit upgrades are a strict next-generation chain, not a menu
        # of every later unit. Preserve that behavior for Era 11-20.
        prefix=uid.rsplit('_',1)[0]+'_'; tier=trailing_int(uid)
        nxt=[f'{prefix}{tier+1}'] if tier < 20 else []
        set_pair(base,'upgrades',atom_block(nxt))
        return base

    def generate_units(self)->None:
        for row in self.unit_rows:self.generated_unit_blocks[row['unit_id']]=self.generate_unit(row)

    def write_units(self)->None:
        outdir=self.output/'common/combat_unit_types';outdir.mkdir(parents=True,exist_ok=True)
        bykind=defaultdict(list)
        for row in self.unit_rows:
            kind='airforce' if 'airforce' in row['unit_id'] else 'artillery' if 'artillery' in row['unit_id'] else 'infantry'
            bykind[kind].append(row)
        final_old={'infantry':'combat_unit_type_infantry_10','airforce':'combat_unit_type_airforce_10','artillery':'combat_unit_type_artillery_10'}
        for kind,rows in bykind.items():
            lines=[f"# Generated Era 11-20 {kind} combat units\n\n"]
            # The live Era-10 unit upgrades only into Era 11; each generated
            # unit then upgrades into its immediate successor.
            lines.append(f"INJECT:{final_old[kind]} = {{\n\tupgrades = {{\n\t\t{rows[0]['unit_id']}\n\t}}\n}}\n\n")
            for row in rows:
                lines.append(serialize_definition(row['unit_id'],self.generated_unit_blocks[row['unit_id']]))
                lines.append('\n')
            (outdir/f'z_modern_{kind}_unit_types_era11_20.txt').write_text(''.join(lines),encoding='utf-8')

    # ------------------------- ships -------------------------
    def ship_baseline_id(self,cls:str)->str:
        return {'submarine':'ship_type_submarine_10','destroyer':'ship_type_destroyer_10','cruiser':'ship_type_cruiser_10','battleship':'ship_type_battleship_10','aircraft_carrier':'ship_type_aircraft_carrier_8','troop_ship':'ship_type_troop_ship_2'}[cls]

    def set_path_numeric(self,block:Block,path:str,value:float)->None:
        parts=path.split('.')
        cur=block
        for p in parts[:-1]:
            nb=get_block(cur,p,create=True);assert nb;cur=nb
        set_pair(cur,parts[-1],value)

    def generate_ship(self,row:dict[str,str])->Block:
        cls=row['class'];bid=self.ship_baseline_id(cls)
        if bid not in self.ship_defs:raise RuntimeError(f"Missing ship baseline {bid}")
        b=copy.deepcopy(self.ship_defs[bid])
        stats=parse_semicolon_map(row['stats'])
        for path,v in stats.items():self.set_path_numeric(b,path,v)
        set_pair(b,'unlocking_technologies',atom_block([row['tech_id']]))
        # Obsolescence based on next planned ship in same class.
        same=[x for x in self.ship_rows if x['class']==cls]
        idx=next(i for i,x in enumerate(same) if x['ship_id']==row['ship_id'])
        if idx+1<len(same):
            nxt=same[idx+1]['tech_id']
            set_pair(b,'is_obsolete',Block([Pair('has_technology_researched',Atom(nxt))]))
        else:remove_key(b,'is_obsolete')
        # Icon/profile fields are intentionally untouched: reuse final live graphics.
        return b

    def generate_ships(self)->None:
        for row in self.ship_rows:self.generated_ship_blocks[row['ship_id']]=self.generate_ship(row)

    def write_ships(self)->None:
        outdir=self.output/'common/ship_types';outdir.mkdir(parents=True,exist_ok=True)
        bycls=defaultdict(list)
        for row in self.ship_rows:bycls[row['class']].append(row)
        for cls,rows in bycls.items():
            lines=[f"# Generated Era 11-20 {cls} ships. Graphics inherited from live final ship.\n\n"]
            old=self.ship_baseline_id(cls)
            firsttech=rows[0]['tech_id']
            lines.append(f"INJECT:{old} = {{\n\tis_obsolete = {{ has_technology_researched = {firsttech} }}\n}}\n\n")
            for row in rows:
                lines.append(serialize_definition(row['ship_id'],self.generated_ship_blocks[row['ship_id']]))
                lines.append('\n')
            (outdir/f'z_modern_{cls}_ships_era11_20.txt').write_text(''.join(lines),encoding='utf-8')

    # ------------------------- mobilization -------------------------
    def mob_equipment_switch_effect(self, multiplier:str='-0.5')->Block:
        return Block([Pair('custom_tooltip',Block([
            Pair('text',Atom('mobilization_option_it_hurts_organization_when_you_adjust_equipment_tt')),
            Pair('add_organization',Block([Pair('value',Atom('organization')),Pair('multiply',Atom(multiplier))]))
        ]))])

    def mob_market_supply_block(self, goods:list[str])->Block:
        # CWE's live options gate equipment on market potential supply. Keep that
        # behavior for every newly consumed good rather than making future options
        # universally selectable.
        market=Block([])
        for good in goods:
            market.items.append(Pair(f'mg:{good} ?=',Block([Pair('has_potential_supply',Atom('yes'))])))
        return market

    def mob_scaffold_template(self,row:dict[str,str])->Block:
        # If raw current CWE mobilization source was supplied, clone the named live
        # template exactly. Otherwise reconstruct the relevant live semantics rather
        # than falling back to possible={always=yes}.
        scaffold=row['scaffold'].lower()
        group=row['group']
        candidates=[]
        if 'air_transport' in scaffold or 'air-transport' in scaffold:candidates=['mobilization_option_air_transport']
        elif 'aerial_recon' in scaffold:candidates=['mobilization_option_aerial_recon']
        elif 'digital_cryptography' in scaffold:candidates=['mobilization_option_digital_cryptography_recon']
        elif 'field_hospitals' in scaffold:candidates=['mobilization_option_field_hospitals']
        elif 'drones' in scaffold:candidates=['mobilization_option_drones']
        elif 'specialist_support' in scaffold:candidates=['mobilization_option_special_forces','mobilization_option_cyber_forces']
        elif 'special_weapons' in scaffold:candidates=['mobilization_option_drones','mobilization_option_machinegunners']
        elif 'transport' in scaffold:candidates=['mobilization_option_truck_transport','mobilization_option_air_transport']
        elif 'recon' in scaffold:candidates=['mobilization_option_aerial_recon']
        for c in candidates:
            if c in self.mob_defs:return copy.deepcopy(self.mob_defs[c])

        b=Block([])
        set_pair(b,'texture',quote('gfx/interface/icons/production_method_icons/modern_future/technique_i.png'))
        if group == 'transport':
            set_pair(b,'on_activate_while_mobilized',self.mob_equipment_switch_effect())
        elif group == 'medic_support':
            set_pair(b,'on_activate_while_mobilized',Block([Pair('custom_tooltip',Block([
                Pair('text',Atom('mobilization_option_it_hurts_organization_to_add_medic_support_tt')),
                Pair('add_organization',Block([Pair('value',Atom('organization')),Pair('multiply',Atom('-0.25'))]))
            ]))]))
            set_pair(b,'on_deactivate',Block([Pair('custom_tooltip',Block([
                Pair('text',Atom('mobilization_option_it_hurts_morale_and_organization_when_you_remove_medic_support_tt')),
                Pair('every_combat_unit',Block([Pair('add_morale',Block([Pair('value',Atom('morale')),Pair('multiply',Atom('-0.5'))]))])),
                Pair('add_organization',Block([Pair('value',Atom('organization')),Pair('multiply',Atom('-0.25'))]))
            ]))]))
        else:
            oa=self.mob_equipment_switch_effect()
            set_pair(b,'on_activate_while_mobilized',oa)
            set_pair(b,'on_deactivate',copy.deepcopy(oa))
        set_pair(b,'ai_weight',Block([Pair('value',Atom('1'))]))
        return b

    def generate_mob(self,row:dict[str,str])->Block:
        b=self.mob_scaffold_template(row)
        # Use a shared technique card for mobilization options.
        set_pair(b,'texture',quote('gfx/interface/icons/production_method_icons/modern_future/technique_i.png'))
        set_pair(b,'unlocking_technologies',atom_block([row['tech_id']]))
        set_pair(b,'group',row['group'])
        stats=parse_semicolon_map(row['stats'])
        up=Block([]); unit=Block([])
        goods_names={'aeroplanes','oil','software','computers','warplanes','advanced_weaponry','industrial_robots','electricity','automobiles','communication_services','artillery','ammunition','pharmaceuticals','telecommunications'}
        consumed_goods=[]
        for k,v in stats.items():
            if k in goods_names:
                set_pair(up,f'goods_input_{k}_add',v); consumed_goods.append(k)
            else:set_pair(unit,k,v)
        set_pair(b,'upkeep_modifier',up)
        set_pair(b,'unit_modifier',unit)

        # Rebuild `possible` from the future option's actual goods so the cloned
        # template cannot retain stale supply checks for its old equipment.
        possible=Block([])
        if row['group']=='transport':
            possible.items.append(Pair('scope:military_formation',Block([
                Pair('NOT',Block([Pair('has_mobilization_option',Atom('mobilization_option:mobilization_option_forced_march'))]))
            ])))
        elif row['group']=='medic_support':
            possible.items.append(Pair('NOT',Block([Pair('scope:military_formation',Block([
                Pair('has_mobilization_option',Atom('mobilization_option:mobilization_option_first_aid'))
            ]))])))
        if consumed_goods:
            possible.items.append(Pair('market ?=',self.mob_market_supply_block(consumed_goods)))
        set_pair(b,'possible',possible)

        if get_block(b,'ai_weight') is None:set_pair(b,'ai_weight',Block([Pair('value',Atom('1'))]))
        return b

    def generate_mobilization(self)->None:
        for row in self.mob_rows:self.generated_mob_blocks[row['id']]=self.generate_mob(row)

    def write_mobilization(self)->None:
        outdir=self.output/'common/mobilization_options';outdir.mkdir(parents=True,exist_ok=True)
        lines=['# Generated Era 11-20 mobilization options\n\n']
        for row in self.mob_rows:
            text=serialize_definition(row['id'],self.generated_mob_blocks[row['id']])
            # The lightweight AST treats Jomini's optional-scope `?=` token as
            # part of the key; normalize the serializer's extra `=` here.
            text=re.sub(r'(\b(?:market|mg:[A-Za-z0-9_]+) \?=) =',r'\1',text)
            lines.append(text)
            lines.append('\n')
        (outdir/'z_modern_mobilization_options_era11_20.txt').write_text(''.join(lines),encoding='utf-8')

    # ------------------------- localization -------------------------
    def write_localization(self)->None:
        outdir=self.output/'localization/english';outdir.mkdir(parents=True,exist_ok=True)
        tech=['l_english:\n']
        for row in self.tech_rows:
            tech.append(f" {row['tech_id']}:0 {quote(row['localized_name'])}\n")
            tech.append(f" {row['tech_id']}_desc:0 {quote(row['description'])}\n")
        (outdir/'z_modern_era11_20_techs_l_english.yml').write_text(''.join(tech),encoding='utf-8-sig')
        content=['l_english:\n']
        for row in self.pm_rows:content.append(f" {row['pm_id']}:0 {quote(row['localized_name'])}\n")
        for row in self.unit_rows:
            content.append(f" {row['unit_id']}:0 {quote(row['localized_name'])}\n")
            content.append(f" {row['unit_id']}_desc:0 {quote(row['description'])}\n")
        for row in self.ship_rows:
            content.append(f" {row['ship_id']}:0 {quote(row['localized_name'])}\n")
            content.append(f" {row['ship_id']}_desc:0 {quote(row['description'])}\n")
        for row in self.mob_rows:content.append(f" {row['id']}:0 {quote(row['name'])}\n")
        (outdir/'z_modern_era11_20_content_l_english.yml').write_text(''.join(content),encoding='utf-8-sig')

    # ------------------------- graphics -------------------------
    def generate_graphics(self)->None:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as e:
            raise RuntimeError('Pillow is required to generate the requested PNG graphics') from e
        pm_dir=self.output/'gfx/interface/icons/production_method_icons/modern_future';pm_dir.mkdir(parents=True,exist_ok=True)
        unit_dir=self.output/'gfx/unit_illustrations/modern_future';unit_dir.mkdir(parents=True,exist_ok=True)
        font_candidates=[Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf')]
        font_path=next((p for p in font_candidates if p.exists()),None)
        if not font_path:raise RuntimeError('No system font found for icon generation')
        def card(path:Path,numeral:str,label:str,size=256):
            img=Image.new('RGBA',(size,size),(25,30,38,255));d=ImageDraw.Draw(img)
            d.rounded_rectangle((8,8,size-9,size-9),radius=28,outline=(210,218,230,255),width=4)
            # subtle horizontal divider
            d.line((32,size*0.70,size-32,size*0.70),fill=(120,130,145,255),width=2)
            f1=ImageFont.truetype(str(font_path),96 if len(numeral)<=3 else 78)
            f2=ImageFont.truetype(str(font_path),28 if len(label)<=12 else 22)
            bb=d.textbbox((0,0),numeral,font=f1);x=(size-(bb[2]-bb[0]))/2;y=28
            d.text((x,y),numeral,font=f1,fill=(242,244,248,255))
            bb2=d.textbbox((0,0),label,font=f2);x2=(size-(bb2[2]-bb2[0]))/2;y2=size*0.77
            d.text((x2,y2),label,font=f2,fill=(205,211,220,255))
            img.save(path,'PNG',optimize=True)
        # PM cards I-XX shared across all PMs.
        for n in range(1,21):
            rn=roman(n).lower()
            for stem,label in [('good','Good'),('technique','Technique'),('automation','Automation'),('organization','Organization')]:
                card(pm_dir/f'{stem}_{rn}.png',roman(n),label)
        # Unit cards XI-XX, differentiated by actual unit type.
        for n in range(11,21):
            rn=roman(n).lower()
            for stem,label in [('infantry','Infantry'),('air','Air Unit'),('artillery','Artillery')]:
                card(unit_dir/f'{stem}_{rn}.png',roman(n),label)

    # ------------------------- validation -------------------------
    def validate(self)->None:
        errors=[];warnings=[]
        if len(self.generated_tech_blocks)!=260:errors.append(f"Expected 260 techs, got {len(self.generated_tech_blocks)}")
        if len(self.generated_pm_blocks)!=592:errors.append(f"Expected 592 PMs, got {len(self.generated_pm_blocks)}")
        if len(self.generated_unit_blocks)!=30:errors.append(f"Expected 30 units, got {len(self.generated_unit_blocks)}")
        if len(self.generated_ship_blocks)!=52:errors.append(f"Expected 52 ships, got {len(self.generated_ship_blocks)}")
        if len(self.generated_mob_blocks)!=10:errors.append(f"Expected 10 mobilization options, got {len(self.generated_mob_blocks)}")
        # IDs unique/noncolliding
        for name,generated,source in [('PM',self.generated_pm_blocks,self.pm_defs),('tech',self.generated_tech_blocks,self.tech_defs),('unit',self.generated_unit_blocks,self.unit_defs),('ship',self.generated_ship_blocks,self.ship_defs)]:
            collisions=set(generated)&set(source)
            if collisions:errors.append(f"{name} collisions: {sorted(collisions)[:10]}")
        # PMG active and reachability
        for row in self.pm_rows:
            if row['pmg'] not in self.active_pmgs:errors.append(f"Inactive PMG target {row['pmg']} for {row['pm_id']}")
            if self.baseline_pm.get(row['pmg']) is None:errors.append(f"No baseline {row['pmg']}")
        # Tech chains continuous
        techids=set(self.generated_tech_blocks)|set(self.tech_defs)
        for row in self.tech_rows:
            if row['prerequisite'] not in techids:errors.append(f"Missing tech prerequisite {row['prerequisite']} for {row['tech_id']}")
        # Generated PM unlock techs valid
        for row in self.pm_rows:
            if row['tech_id'] not in self.generated_tech_blocks:errors.append(f"PM {row['pm_id']} references missing {row['tech_id']}")

        # Semantic PM audit: a building-level goods output multiplier is only valid
        # when at least one active PM on the host building actually produces goods.
        def contains_key_prefix(block: Block, prefix: str) -> bool:
            for item in block.items:
                if isinstance(item, Pair):
                    if item.key.startswith(prefix):
                        return True
                    if isinstance(item.value, Block) and contains_key_prefix(item.value, prefix):
                        return True
            return False

        pmg_to_buildings: dict[str, list[str]] = defaultdict(list)
        for bid, building in self.building_defs.items():
            pgb = get_block(building, 'production_method_groups')
            if pgb:
                for pmg in block_atoms(pgb):
                    pmg_to_buildings[pmg].append(bid)

        def building_has_market_goods_output(bid: str) -> bool:
            building = self.building_defs[bid]
            pgb = get_block(building, 'production_method_groups')
            if not pgb:
                return False
            for pmg in block_atoms(pgb):
                pmgb = self.pmg_defs.get(pmg)
                if not pmgb:
                    continue
                methods = get_block(pmgb, 'production_methods')
                if not methods:
                    continue
                for pid in block_atoms(methods):
                    srcpm = self.pm_defs.get(pid)
                    if srcpm and contains_key_prefix(srcpm, 'goods_output_'):
                        return True
            return False

        for row in self.pm_rows:
            pm = self.generated_pm_blocks[row['pm_id']]
            if contains_key_prefix(pm, 'goods_output_mult'):
                hosts = pmg_to_buildings.get(row['pmg'], [])
                if hosts and not any(building_has_market_goods_output(bid) for bid in hosts):
                    errors.append(f"Semantically inert goods_output_mult on {row['pm_id']} ({row['pmg']})")

            # Every future PM must change mechanics beyond texture/unlock metadata.
            baseline = self.baseline_pm_block(row['pmg'])
            current = copy.deepcopy(pm)
            for b in (baseline, current):
                remove_key(b, 'texture')
                remove_key(b, 'unlocking_technologies')
            if serialize_block(baseline) == serialize_block(current):
                errors.append(f"Future PM has no mechanical delta from live baseline: {row['pm_id']}")

        # V3 arithmetic-progression audit. For every PMG with multiple future
        # generations, the direct goods package must move by the exact same
        # absolute amount from the live endpoint -> first future PM -> every
        # subsequent future PM. No new goods input/output may regress.
        progression_audit_rows: list[dict[str,str]] = []
        future_by_pmg: dict[str,list[dict[str,str]]] = defaultdict(list)
        for row in self.pm_rows:
            future_by_pmg[row['pmg']].append(row)

        for pmg, rows in sorted(future_by_pmg.items()):
            if pmg in self.market_goods_pmgs:
                source_ids = self.source_market_pm_ids(pmg)
                anchor_id = source_ids[-1]
                try:
                    expected_deltas, derivation_mode, source_refs = self.linear_market_goods_deltas(pmg)
                except RuntimeError as exc:
                    errors.append(f"Linear-rule resolution failed for {pmg}: {exc}")
                    continue
            else:
                source_ids = [pid for pid in self.pmg_methods.get(pmg, []) if pid in self.pm_defs]
                anchor_id = self.baseline_pm.get(pmg) or (source_ids[-1] if source_ids else '')
                recent = self.recent_three_direct_goods_deltas(pmg)
                if recent:
                    expected_deltas, source_refs = recent
                    derivation_mode = 'last-three-live-inputs'
                else:
                    source_refs = source_ids[-3:]
                    derivation_mode = 'explicit-domain-rule'
                    expected_deltas = {}

            anchor_profile = self.source_goods_profile(anchor_id) if anchor_id else {}
            generated_profiles = [self.goods_profile_from_block(self.generated_pm_blocks[r['pm_id']]) for r in rows]
            seq = [anchor_profile] + generated_profiles
            all_paths: set[tuple[str,str]] = set().union(*(set(profile) for profile in seq)) if seq else set()
            delta_map: dict[tuple[str,str],float] = {}
            pmg_ok = True
            for path in sorted(all_paths):
                vals = [profile.get(path, 0.0) for profile in seq]
                if len(vals) < 2:
                    continue
                diffs = [vals[i+1] - vals[i] for i in range(len(vals)-1)]
                delta_map[path] = diffs[0]
                if any(delta < -1e-8 for delta in diffs):
                    errors.append(f"Goods regression in {pmg} {path[1]}: {vals}")
                    pmg_ok = False
                if len(diffs) > 1 and any(abs(delta - diffs[0]) > 1e-8 for delta in diffs[1:]):
                    errors.append(f"Non-linear future goods progression in {pmg} {path[1]}: values={vals} deltas={diffs}")
                    pmg_ok = False

            # Mature auto-derived families must exactly match the slope obtained
            # from the latest three productive live PMs.
            if derivation_mode in ('last-three-live', 'last-three-live-inputs'):
                for path, expected in expected_deltas.items():
                    got = delta_map.get(path, 0.0)
                    if abs(got - expected) > 1e-8:
                        errors.append(f"Last-three continuation mismatch in {pmg} {path[1]}: expected {expected}, got {got}")
                        pmg_ok = False

            # Productive future PMGs may never output less than the final live PM.
            if pmg in self.market_goods_pmgs and generated_profiles:
                for path, live_value in anchor_profile.items():
                    if not path[1].startswith('goods_output_'):
                        continue
                    if generated_profiles[0].get(path, 0.0) + 1e-8 < live_value:
                        errors.append(f"Future output below live endpoint in {pmg} {path[1]}: {generated_profiles[0].get(path,0.0)} < {live_value}")
                        pmg_ok = False

            def fmt_delta(path: tuple[str,str], value: float) -> str:
                text = f"{value:.6f}".rstrip('0').rstrip('.')
                return f"{path[0]}.{path[1]}={text or '0'}"
            progression_audit_rows.append({
                'pmg': pmg,
                'future_pm_count': str(len(rows)),
                'anchor_pm': anchor_id,
                'derivation_mode': derivation_mode,
                'source_reference_pms': ';'.join(source_refs),
                'per_generation_goods_delta': ';'.join(fmt_delta(path, value) for path, value in sorted(delta_map.items())),
                'status': 'PASS' if pmg_ok else 'FAIL',
            })

        # Compatibility-safe productivity bonuses must name the exact good.
        # The target good must be produced directly by the PMG itself, or by an
        # active Goods PMG on a building hosting an Automation/Organisation PMG.
        def iter_pairs_recursive(block: Block):
            for item in block.items:
                if isinstance(item, Pair):
                    yield item
                    if isinstance(item.value, Block):
                        yield from iter_pairs_recursive(item.value)

        for row in self.pm_rows:
            pm = self.generated_pm_blocks[row['pm_id']]
            allowed_outputs = set(self.output_goods_for_pmg(row['pmg']))
            for pair in iter_pairs_recursive(pm):
                if pair.key == 'goods_output_mult':
                    errors.append(f"Generic goods_output_mult remains on {row['pm_id']}")
                match = re.fullmatch(r'goods_output_(.+)_mult', pair.key)
                if match and match.group(1) not in allowed_outputs:
                    errors.append(f"Invalid per-good output multiplier on {row['pm_id']}: {match.group(1)} not in {sorted(allowed_outputs)}")

        # PM titles are intentionally clean names. Do not append implementation
        # labels such as '— Agriculture', '— Machinists Line', etc.
        for row in self.pm_rows:
            if ' — ' in row['localized_name']:
                errors.append(f"PM localization still contains a type suffix: {row['pm_id']} = {row['localized_name']}")

        # Write the progression ledger even when a later validation check fails.
        rep = self.output/'validation'; rep.mkdir(parents=True, exist_ok=True)
        audit_csv = rep/'PM_LINEAR_PROGRESSION_AUDIT.csv'
        with audit_csv.open('w', newline='', encoding='utf-8-sig') as f:
            fields = ['pmg','future_pm_count','anchor_pm','derivation_mode','source_reference_pms','per_generation_goods_delta','status']
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(progression_audit_rows)
        mode_counts = Counter(row['derivation_mode'] for row in progression_audit_rows)
        audit_md = ['# PM Linear Progression Audit\n\n',
                    'Every PMG with generated PMs is checked from its live endpoint through every future generation. Direct goods inputs/outputs must use one constant absolute delta and may never regress.\n\n',
                    f"- PMGs audited: **{len(progression_audit_rows)}**\n",
                    f"- Last-three live output extrapolation: **{mode_counts.get('last-three-live',0)}**\n",
                    f"- Last-three live input extrapolation: **{mode_counts.get('last-three-live-inputs',0)}**\n",
                    f"- Explicit sparse/flat-family rules: **{mode_counts.get('explicit-half-baseline',0) + mode_counts.get('explicit-family',0)}**\n",
                    f"- Explicit non-market/domain rules: **{mode_counts.get('explicit-domain-rule',0)}**\n",
                    f"- Failed PMGs: **{sum(row['status']=='FAIL' for row in progression_audit_rows)}**\n\n",
                    'See `PM_LINEAR_PROGRESSION_AUDIT.csv` for the source references and exact per-generation delta for every PMG.\n']
        (rep/'PM_LINEAR_PROGRESSION_AUDIT.md').write_text(''.join(audit_md), encoding='utf-8')

        # Explicit output-domain checks for non-goods buildings/slots.
        for row in self.pm_rows:
            pm = self.generated_pm_blocks[row['pm_id']]
            pmg = row['pmg']
            if pmg == 'pmg_base_building_university':
                if not contains_key_prefix(pm, 'country_weekly_innovation_add'):
                    errors.append(f"University base PM missing innovation output: {row['pm_id']}")
            elif pmg == 'pmg_bureaucracy_government':
                if not contains_key_prefix(pm, 'country_bureaucracy_add') or not contains_key_prefix(pm, 'state_tax_capacity_add'):
                    errors.append(f"Bureaucracy PM missing bureaucracy/tax output: {row['pm_id']}")
            elif pmg == 'pmg_essential_services_government':
                if not contains_key_prefix(pm, 'state_pop_qualifications_mult') or not contains_key_prefix(pm, 'state_infrastructure_add'):
                    errors.append(f"Essential-services PM missing public-service effects: {row['pm_id']}")
            elif pmg == 'pmg_security_services_government':
                if not contains_key_prefix(pm, 'state_turmoil_effects_mult'):
                    errors.append(f"Security-services PM missing policing effect: {row['pm_id']}")
            elif pmg == 'pmg_forex_government':
                if not contains_key_prefix(pm, 'country_minting_add'):
                    errors.append(f"Forex PM missing monetary output: {row['pm_id']}")
            elif pmg == 'pmg_base_building_construction_sector_size':
                if not contains_key_prefix(pm, 'country_construction_add'):
                    errors.append(f"Construction-size PM missing construction productivity: {row['pm_id']}")

        # Combat-unit upgrade reachability must be a strict immediate-next chain.
        for row in self.unit_rows:
            uid=row['unit_id']; tier=trailing_int(uid); prefix=uid.rsplit('_',1)[0]+'_'
            got=block_atoms(get_block(self.generated_unit_blocks[uid],'upgrades'))
            expected=[f'{prefix}{tier+1}'] if tier < 20 else []
            if got != expected: errors.append(f"Bad unit upgrade chain {uid}: {got} vs {expected}")
        # Forbidden residue search
        alltext='\n'.join(p.read_text(encoding='utf-8-sig',errors='replace') for p in self.output.rglob('*.txt'))
        for pat in KNOWN_FORBIDDEN_GENERATED_PATTERNS:
            if re.search(pat,alltext):errors.append(f"Forbidden deprecated/dangling reference matched: {pat}")
        # Specific future-risk keys
        futuretech='\n'.join(serialize_definition(k,v) for k,v in self.generated_tech_blocks.items())
        for bad in ('state_expected_sol_mult','state_working_adult_ratio_add','state_urbanization_per_level_mult'):
            # These keys may appear nowhere in new output under specified replacement chains.
            if bad in futuretech:errors.append(f"Forbidden future modifier generated: {bad}")
        # Technology art reuse: compare generated to source Era10 per chain.
        for row in self.tech_rows:
            b=self.generated_tech_blocks[row['tech_id']];src=self.source_tech_template(row['chain'],10)
            if get_atom(b,'texture')!=get_atom(src,'texture'):errors.append(f"Tech texture mismatch {row['tech_id']}")
        # ship graphics reuse
        for row in self.ship_rows:
            b=self.generated_ship_blocks[row['ship_id']];src=self.ship_defs[self.ship_baseline_id(row['class'])]
            for key in ('icon','profile_texture'):
                if get_atom(b,key)!=get_atom(src,key):errors.append(f"Ship {row['ship_id']} did not reuse {key}")
        # Localization must remain in-world. Never expose implementation eras,
        # deprecated content, or mod-development language to the player.
        lore_forbidden = re.compile(r'\bEra\s*\d+\b|\bCWE\b|deprecated|live cadence|technological era|production method series', re.I)
        for row in self.tech_rows:
            if lore_forbidden.search(row['description']):
                errors.append(f"Out-of-world technology description: {row['tech_id']}")
        for row in self.unit_rows:
            if lore_forbidden.search(row['description']):
                errors.append(f"Out-of-world unit description: {row['unit_id']}")
        for row in self.ship_rows:
            if lore_forbidden.search(row.get('description','')):
                errors.append(f"Out-of-world ship description: {row['ship_id']}")

        # Graphics references exist.
        for row in self.pm_rows:
            if not (self.output/self.pm_icon_path(row)).exists():errors.append(f"Missing PM icon {self.pm_icon_path(row)}")
        for row in self.unit_rows:
            if not (self.output/self.unit_icon_path(row['unit_id'])).exists():errors.append(f"Missing unit icon {self.unit_icon_path(row['unit_id'])}")
        # brace parse all generated txts
        for path in self.output.rglob('*.txt'):
            try:parse_file(path)
            except Exception as e:errors.append(f"Parse failure {path.relative_to(self.output)}: {e}")
        self.validation={'errors':errors,'warnings':warnings,'counts':{
            'technologies':len(self.generated_tech_blocks),'production_methods':len(self.generated_pm_blocks),'combat_units':len(self.generated_unit_blocks),'ships':len(self.generated_ship_blocks),'mobilization_options':len(self.generated_mob_blocks),'active_pmgs':len(self.active_pmgs)
        }}
        rep=self.output/'validation';rep.mkdir(parents=True,exist_ok=True)
        (rep/'validation.json').write_text(json.dumps(self.validation,indent=2),encoding='utf-8')
        lines=['# CWE Era 11-20 Post-Generation Validation\n\n']
        for k,v in self.validation['counts'].items():lines.append(f"- **{k}:** {v}\n")
        lines.append(f"- **errors:** {len(errors)}\n- **warnings:** {len(warnings)}\n\n")
        if errors:
            lines.append('## Errors\n');lines.extend(f"- {e}\n" for e in errors)
        else:lines.append('## Result\n\nPASS — no structural validation errors detected.\n')
        (rep/'VALIDATION_REPORT.md').write_text(''.join(lines),encoding='utf-8')
        if errors:raise RuntimeError(f"Validation failed with {len(errors)} error(s); see {rep/'VALIDATION_REPORT.md'}")

    def write_manifest_report(self)->None:
        files=[]
        for p in sorted(self.output.rglob('*')):
            if p.is_file():files.append({'path':str(p.relative_to(self.output)),'bytes':p.stat().st_size})
        rep=self.output/'validation';rep.mkdir(parents=True,exist_ok=True)
        (rep/'generated_file_manifest.json').write_text(json.dumps(files,indent=2),encoding='utf-8')

    def write_readme(self)->None:
        txt="""# CWE Era 11-20 generated patch\n\nThis folder is the generated compatibility patch implementing the approved Era 11-20 plan.\n\n- Era 1-10 fixes are modifier-only `INJECT`s.\n- Era 11-20 technologies are new definitions.\n- New PMs use `pm_modern_...` IDs and are appended only to live PMGs via `INJECT`.\n- Mature PM direct-goods packages continue arithmetically from the latest three usable live PMs; sparse/flat families use fixed source-relative rules.\n- Generic `goods_output_mult` is forbidden; productivity bonuses use exact `goods_output_<good>_mult` modifiers derived from live productive PMGs. +10% bonus families rise by +5 percentage points per successive future PM; +20% families rise by +10 points per PM.\n- Deprecated/dangling PMs and unused PMGs are never restored.\n- Army/air/artillery use generated Roman-numeral PNG cards.\n- Production methods use shared Roman-numeral `Good`, `Technique`, `Automation`, and `Organization` PNG cards.\n- Ships reuse the final live ship graphics for their class.\n- Future technologies reuse each chain's Era-10 technology texture.\n\n## Regeneration\nRun `python tools/generate_era11_20.py --source <current CWE root> --output <output root> --manifests manifests`. The generator re-reads live PMGs, source PM baselines, Era-10 technology art/modifiers, units and ships.\n\nTechnology eras use the approved Modern CWE curve `round(5000 * era^1.20, nearest 500)`, with explicit project-approved values from Era 1 through Era 20. Era 1-10 are emitted as `REPLACE` definitions so the same generator owns the full era schedule.\n"""
        (self.output/'README_IMPLEMENTATION.md').write_text(txt,encoding='utf-8')

    def run(self)->None:
        # clean generated content but preserve tool/manifests if output points to a package root
        for child in ['common','localization','gfx','validation']:
            p=self.output/child
            if p.exists():shutil.rmtree(p)
        self.generate_technologies();self.write_eras();self.write_technology_files();self.write_old_tech_fixes()
        self.generate_pms();self.write_pm_files();self.write_pmg_injections()
        self.generate_units();self.write_units()
        self.generate_ships();self.write_ships()
        self.generate_mobilization();self.write_mobilization()
        self.write_localization();self.generate_graphics();self.write_readme()
        self.validate();self.write_manifest_report()


def main():
    here=Path(__file__).resolve().parent.parent
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',type=Path,required=True,help='Current CWE source root containing common/, localization/, gfx/')
    ap.add_argument('--output',type=Path,default=here,help='Generated patch root')
    ap.add_argument('--manifests',type=Path,default=here/'manifests',help='Design manifest directory')
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    gen=Generator(args.source.resolve(),args.output.resolve(),args.manifests.resolve())
    gen.run()
    print(json.dumps(gen.validation,indent=2))

if __name__=='__main__':
    main()
