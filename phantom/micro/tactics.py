from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot

type Tactic = Callable[[Unit], Action | None]


@dataclass(frozen=True)
class Until:
    time: int
    tactic: Tactic

    def __call__(self, unit: Unit) -> Action | None:
        if unit.game_loop < self.time * 22.4:
            return self.tactic(unit)
        return None


class Tactics:
    def __init__(self, bot: PhantomBot) -> None:
        self.bot = bot
        self._registry = defaultdict[UnitTypeId, list[Tactic]](list)
        self._assignment = dict[int, Tactic]()

    def register(self, unit_type: UnitTypeId, tactic: Tactic) -> None:
        self._registry[unit_type].append(tactic)

    def on_unit_created(self, unit: Unit) -> None:
        registered = self._registry[unit.type_id]
        if not registered:
            return
        self._assignment[unit.tag] = registered.pop(0)

    def on_step(self, observation: Observation) -> None:
        pass

    def get_actions(self, observation: Observation) -> Mapping[Unit, Action]:
        actions = dict[Unit, Action]()
        for tag, tactic in list(self._assignment.items()):
            if unit := self.bot.unit_tag_dict.get(tag):
                if action := tactic(unit):
                    actions[unit] = action
            else:
                del self._assignment[tag]
        return actions
