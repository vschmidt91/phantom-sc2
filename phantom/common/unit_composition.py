from collections import Counter
from collections.abc import Mapping

from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units

type UnitComposition = Mapping[UnitTypeId, float]


def composition_of(units: Units) -> UnitComposition:
    return Counter[UnitTypeId](u.type_id for u in units)


def add_compositions(a: UnitComposition, b: UnitComposition) -> UnitComposition:
    return {k: a.get(k, 0.0) + b.get(k, 0.0) for k in set(a) | set(b)}


def sub_compositions(a: UnitComposition, b: UnitComposition) -> UnitComposition:
    return {k: max(0.0, a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b)}
