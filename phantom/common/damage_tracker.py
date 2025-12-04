from sc2.unit import Unit


class DamageTracker:
    def __init__(self) -> None:
        self._last_damage = dict[int, int]()

    def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        self._last_damage[unit.tag] = unit.game_loop

    def time_since_last_damage(self, unit: Unit) -> int:
        return unit.game_loop - self._last_damage.get(unit.tag, 0)
