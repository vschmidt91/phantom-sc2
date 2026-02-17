from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

AIR_RANGE_OVERRIDE = {
    UnitTypeId.BATTLECRUISER: 6.0,
    UnitTypeId.BUNKER: 5.0,
    UnitTypeId.SENTRY: 5.0,
    UnitTypeId.VOIDRAY: 6.0,
}


def air_range_of(unit: Unit) -> float:
    return AIR_RANGE_OVERRIDE.get(unit.type_id, unit.air_range)
