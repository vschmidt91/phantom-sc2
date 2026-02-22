from collections.abc import Sequence
from typing import Protocol


class HasHealthShield(Protocol):
    health: float
    shield: float


def predict_outcome(units1: Sequence[HasHealthShield], units2: Sequence[HasHealthShield]) -> float:
    hp1 = sum(float(unit.health + unit.shield) for unit in units1)
    hp2 = sum(float(unit.health + unit.shield) for unit in units2)
    total = hp1 + hp2
    if total <= 0:
        return 0.0
    return (hp1 - hp2) / total
