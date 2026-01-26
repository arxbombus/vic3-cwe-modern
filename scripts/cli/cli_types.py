from __future__ import annotations

from enum import Enum


class SaveMode(str, Enum):
    preserve = "preserve"
    canonical = "canonical"


class OperatorChoice(str, Enum):
    eq = "="
    ne = "!="
    gt = ">"
    ge = ">="
    lt = "<"
    le = "<="
