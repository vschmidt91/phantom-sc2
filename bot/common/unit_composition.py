from dataclasses import dataclass
from typing import Counter, Iterable, Mapping

from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit


@dataclass(frozen=True)
class UnitComposition(Mapping[UnitTypeId, float]):

    _items: dict[UnitTypeId, float]

    def __add__(self, other: Mapping[UnitTypeId, float]) -> "UnitComposition":
        return UnitComposition({k: self.get(k, 0.0) + other.get(k, 0.0) for k in set(self._items) | set(other)})

    def __sub__(self, other: Mapping[UnitTypeId, float]) -> "UnitComposition":
        return UnitComposition(
            {k: max(0.0, self._items.get(k, 0.0) - other.get(k, 0.0)) for k in set(self._items) | set(other)}
        )

    def __mul__(self, other: float) -> "UnitComposition":
        return UnitComposition({k: v * other for k, v in self.items()})

    @classmethod
    def of(cls, units: Iterable[Unit]) -> "UnitComposition":
        return UnitComposition(dict(Counter[UnitTypeId](u.type_id for u in units)))

    def __getitem__(self, __key):
        return self._items.get(__key, 0.0)

    def __len__(self):
        return self._items.__len__()

    def __iter__(self):
        return self._items.__iter__()
