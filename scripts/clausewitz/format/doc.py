"""Doc tree + renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

type Mode = Literal["flat", "break"]


@dataclass(frozen=True, slots=True)
class Text:
    s: str


@dataclass(frozen=True, slots=True)
class Concat:
    parts: tuple[Doc, ...]


@dataclass(frozen=True, slots=True)
class Line:
    """Always breaks when rendered."""

    pass


@dataclass(frozen=True, slots=True)
class SoftLine:
    """Breaks in 'break' mode; becomes a single space in 'flat' mode."""

    pass


@dataclass(frozen=True, slots=True)
class Group:
    """Try to render child in 'flat' mode if it fits; else 'break' mode."""

    child: Doc


@dataclass(frozen=True, slots=True)
class Indent:
    """Increase indentation for any line breaks within child."""

    child: Doc
    by: int = 4


type Doc = Text | Concat | Line | SoftLine | Group | Indent


def text(s: str) -> Doc:
    return Text(s)


def concat(*parts: Doc) -> Doc:
    flat: list[Doc] = []
    for p in parts:
        if isinstance(p, Concat):
            flat.extend(p.parts)
        else:
            flat.append(p)
    return Concat(tuple(flat))


def join(sep: Doc, parts: Iterable[Doc]) -> Doc:
    out: list[Doc] = []
    first = True
    for p in parts:
        if first:
            out.append(p)
            first = False
        else:
            out.append(sep)
            out.append(p)
    return concat(*out) if out else text("")


def group(d: Doc) -> Doc:
    return Group(d)


def indent(d: Doc, by: int = 4) -> Doc:
    return Indent(d, by=by)


def line() -> Doc:
    return Line()


def softline() -> Doc:
    return SoftLine()


@dataclass(frozen=True, slots=True)
class _Frame:
    indent: int
    mode: Mode
    doc: Doc


def render(doc: Doc, *, max_width: int = 100) -> str:
    """Render doc into a string with max_width line wrapping."""
    out: list[str] = []
    col = 0

    stack: list[_Frame] = [_Frame(indent=0, mode="break", doc=doc)]

    while stack:
        frame = stack.pop()
        ind, mode, d = frame.indent, frame.mode, frame.doc

        if isinstance(d, Text):
            out.append(d.s)
            col += len(d.s)
            continue

        if isinstance(d, Concat):
            # push in reverse so first part is processed first
            for p in reversed(d.parts):
                stack.append(_Frame(ind, mode, p))
            continue

        if isinstance(d, Line):
            out.append("\n")
            out.append(" " * ind)
            col = ind
            continue

        if isinstance(d, SoftLine):
            if mode == "flat":
                out.append(" ")
                col += 1
            else:
                out.append("\n")
                out.append(" " * ind)
                col = ind
            continue

        if isinstance(d, Indent):
            stack.append(_Frame(ind + d.by, mode, d.child))
            continue

        # Group
        if _fits(max_width, col, stack, _Frame(ind, "flat", d.child)):
            stack.append(_Frame(ind, "flat", d.child))
        else:
            stack.append(_Frame(ind, "break", d.child))
        continue

    return "".join(out)


def _fits(max_width: int, col: int, stack: list[_Frame], first: _Frame) -> bool:
    """
    Lookahead: simulate rendering (without producing output) until:
    - we exceed max_width => doesn't fit
    - we hit a hard Line in break mode => fits (since it will break anyway).
    """
    remaining = max_width - col
    if remaining < 0:
        return False

    probe: list[_Frame] = [first, *reversed(stack)]  # cheap-ish snapshot; ok for v1
    used = 0

    while probe:
        fr = probe.pop()
        d = fr.doc

        if isinstance(d, Text):
            used += len(d.s)
            if used > remaining:
                return False
            continue

        if isinstance(d, Concat):
            for p in reversed(d.parts):
                probe.append(_Frame(fr.indent, fr.mode, p))
            continue

        if isinstance(d, Line):
            # Hard line means we'd break; consider it fitting
            return True

        if isinstance(d, SoftLine):
            if fr.mode == "flat":
                used += 1
                if used > remaining:
                    return False
            else:
                return True
            continue

        if isinstance(d, Indent):
            probe.append(_Frame(fr.indent + d.by, fr.mode, d.child))
            continue

        probe.append(_Frame(fr.indent, "flat", d.child))
        continue

    return True


__all__ = [
    "Concat",
    "Doc",
    "Group",
    "Indent",
    "Line",
    "SoftLine",
    "Text",
    "concat",
    "group",
    "indent",
    "join",
    "line",
    "render",
    "softline",
    "text",
]
