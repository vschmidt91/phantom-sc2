from sc2.unit import Unit


def remaining(unit: Unit) -> int:
    if unit.is_mineral_field:
        if not unit.is_visible:
            return 1500
        else:
            return unit.mineral_contents
    elif unit.is_vespene_geyser:
        if not unit.is_visible:
            return 2250
        else:
            return unit.vespene_contents
    raise TypeError()
