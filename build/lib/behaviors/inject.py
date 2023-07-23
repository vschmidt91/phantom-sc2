from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.unit_command import UnitCommand

# from ..constants import *
from ..modules.module import AIModule
from ..units.unit import AIUnit

# from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class InjectProvider(AIUnit, ABC):
    def __init__(self, ai: AIBase, state: Unit):
        super().__init__(ai, state)
        self.inject_target: Optional["InjectReciever"] = None

    @abstractmethod
    def can_inject(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_inject_ability(self, reciever: "InjectReciever") -> AbilityId:
        raise NotImplementedError

    def inject(self) -> Optional[UnitCommand]:
        if self.inject_target is None:
            return None
        if self.inject_target.is_snapshot:
            self.inject_target = None
            return None
        if not self.inject_target.wants_inject():
            self.inject_target = None
            return None
        if not self.can_inject():
            if 10 < self.state.position.distance_to(self.inject_target.state.position):
                target = self.inject_target.state.position.towards(
                    self.ai.game_info.map_center,
                    self.state.radius + self.inject_target.state.radius,
                )
                return self.state(AbilityId.MOVE, target)
        ability = self.get_inject_ability(self.inject_target)
        return self.state(ability, self.inject_target.state)


class InjectReciever(AIUnit, ABC):
    @abstractmethod
    def wants_inject(self) -> bool:
        raise NotImplementedError


class InjectManager(AIModule):
    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

    async def on_step(self) -> None:
        self.assign_injects()

    def assign_injects(self) -> None:
        providers = {
            provider
            for provider in self.ai.unit_manager.all(InjectProvider)
            if provider.can_inject() and not provider.inject_target
        }
        recievers_provided = {
            provider.inject_target.state.tag
            for provider in self.ai.unit_manager.all(InjectProvider)
            if provider.inject_target
        }
        recievers = {
            reciever
            for reciever in self.ai.unit_manager.all(InjectReciever)
            if reciever.wants_inject() and reciever.state.tag not in recievers_provided
        }
        while any(providers) and any(recievers):
            provider = max(providers, key=lambda p: p.state.energy)

            reciever = min(
                recievers,
                key=lambda r: r.state.position.distance_to(provider.state.position),
            )

            providers.remove(provider)
            recievers.remove(reciever)

            provider.inject_target = reciever

    # def assign_queen(self) -> None:
    #     injectors = [
    #         unit
    #         for unit in self.ai.unit_manager.units.values()
    #         if isinstance(unit, InjectBehavior)
    #     ]
    #     injected_bases = {q.inject_target for q in injectors}

    #     if not (injector := next((queen for queen in injectors if not queen.inject_target), None)):
    #         return

    #     def base_priority(base: Base) -> float:
    #         return injector.state.position.distance_to(base.position)

    #     bases: Iterable[Base] = (
    #         base
    #         for base in self.ai.resource_manager.bases
    #         if (
    #             base.townhall
    #             and base not in injected_bases
    #             and BuffId.QUEENSPAWNLARVATIMER not in base.townhall.state.buffs
    #         )
    #     )
    #     injector.inject_target = min(
    #         bases,
    #         key=base_priority,
    #         default=None,
    #     )


# class InjectBehavior(AIUnit):
#     def __init__(self, ai: AIBase, unit: Unit):
#         super().__init__(ai, unit)
#         self.inject_target: Optional[Base] = None

#     def inject(self) -> Optional[UnitCommand]:
#         if not self.inject_target:
#             return None

#         if not self.inject_target.townhall:
#             self.inject_target = None
#             return None

#         target = self.inject_target.position.towards(
#             self.inject_target.mineral_patches.position,
#             -(self.inject_target.townhall.state.radius + self.state.radius),
#         )
#         if 10 < self.state.position.distance_to(target):
#             return self.state.move(target)
#         elif self.inject_target.townhall.state.has_buff(BuffId.QUEENSPAWNLARVATIMER):
#             return None
#         elif ENERGY_COST[AbilityId.EFFECT_INJECTLARVA] <= self.state.energy:
#             return self.state(AbilityId.EFFECT_INJECTLARVA, target=self.inject_target.townhall.state)

#         return None
