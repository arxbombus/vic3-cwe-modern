from __future__ import annotations

from importlib import util
from pathlib import Path
import sys
from types import ModuleType
from typing import Iterable

from plan_api import PlanSpec


def _load_module(module_name: str, path: Path) -> ModuleType:
    spec = util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module at {path}")
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_plan_from_module(module: ModuleType, origin: Path) -> PlanSpec:
    get_plan = getattr(module, "get_plan", None)
    if get_plan is None:
        raise ValueError(f"{origin} does not define get_plan()")
    plan = get_plan()
    if not isinstance(plan, PlanSpec):
        raise TypeError(f"{origin} get_plan() did not return PlanSpec")
    return plan


def load_plans(
    paths: Iterable[tuple[str, Path]],
) -> dict[str, PlanSpec]:
    registry: dict[str, PlanSpec] = {}
    for module_prefix, directory in paths:
        if not directory.exists():
            continue
        for file in sorted(directory.glob("*.py")):
            if file.name in {"__init__.py", "common.py"} or file.name.startswith("_"):
                continue
            module_name = f"{module_prefix}.{file.stem}"
            module = _load_module(module_name, file)
            plan = _load_plan_from_module(module, file)
            if plan.id in registry:
                raise ValueError(f"Duplicate plan id: {plan.id}")
            registry[plan.id] = plan
    return registry
