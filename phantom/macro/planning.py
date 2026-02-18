from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action
from phantom.common.utils import MacroId
from phantom.learn.parameters import OptimizationTarget, ParameterManager, Prior
from phantom.macro.builder import Builder, MacroPlan
from phantom.macro.strategy import Strategy, StrategyParameters
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class MacroPlanning:
    def __init__(
        self,
        bot: PhantomBot,
        params: ParameterManager,
        strategy_parameters: StrategyParameters,
        builder: Builder,
        build_order,
    ) -> None:
        self.bot = bot
        self.builder = builder
        self.strategy_parameters = strategy_parameters
        self.build_order = build_order
        self.build_order_completed = False
        self._skip_roach_warren = False

        self.tech_priority_transform = params.optimize[OptimizationTarget.CostEfficiency].add_scalar_transform(
            "tech_priority",
            Prior(0.591, 0.1),
            Prior(0.843, 0.1),
            Prior(-0.097, 0.01),
        )
        self.economy_priority_transform = params.optimize[OptimizationTarget.CostEfficiency].add_scalar_transform(
            "economy_priority",
            Prior(0.842, 0.1),
            Prior(0.148, 0.03),
            Prior(0.039, 0.01),
        )
        self.army_priority_transform = params.optimize[OptimizationTarget.CostEfficiency].add_scalar_transform(
            "army_priority",
            Prior(1.5, 0.1),
            Prior(0.808, 0.1),
            Prior(0.5, 0.1),
        )
        self._army_priority_boost_vs_rush_log = params.optimize[OptimizationTarget.CostEfficiency].add(
            "army_priority_boost_vs_rush_log",
            Prior(0.0, 1.0),
        )
        self._expansion_boost_log = params.optimize[OptimizationTarget.CostEfficiency].add(
            "expansion_boost_log",
            Prior(np.log(0.7), 0.1),
        )

        self._strategy: Strategy | None = None
        self._actions = dict[Unit, Action]()
        self._build_priorities = dict[MacroId, float]()
        self._macro_plans = dict[UnitTypeId, MacroPlan]()

    @property
    def army_priority_boost_vs_rush(self) -> float:
        return np.exp(self._army_priority_boost_vs_rush_log.value)

    @property
    def expansion_boost(self) -> float:
        return np.exp(self._expansion_boost_log.value)

    @property
    def strategy(self) -> Strategy | None:
        return self._strategy

    @property
    def build_priorities(self) -> Mapping[MacroId, float]:
        return self._build_priorities

    @property
    def macro_plans(self) -> Mapping[UnitTypeId, MacroPlan]:
        return self._macro_plans

    def set_skip_roach_warren(self, skip_roach_warren: bool) -> None:
        self._skip_roach_warren = skip_roach_warren

    def on_step(self, observation: Observation) -> None:
        self._actions = {}
        self._build_priorities = {}
        self._macro_plans = {}
        strategy = Strategy(self.bot, self.strategy_parameters)
        self._strategy = strategy

        if not self.build_order_completed:
            nat_unsafe = not self.bot.mediator.is_position_safe(
                grid=self.bot.ground_grid,
                position=self.bot.mediator.get_own_nat,
                weight_safety_limit=10.0,
            )
            if nat_unsafe or self.bot.mediator.get_did_enemy_rush:
                self.build_order_completed = True

            if step := self.build_order.execute(self.bot):
                self._macro_plans.update(step.plans)
                self._build_priorities.update(step.priorities)
                self._actions.update(step.actions)
            else:
                logger.info("Build order completed.")
                self.build_order_completed = True
        else:
            economy_priorities = self.builder.get_priorities(strategy.macro_composition, limit=1.0)
            army_priorities = self.builder.get_priorities(strategy.army_composition, limit=10.0)
            tech_priorities = self.builder.make_upgrades(strategy.composition_target, strategy.filter_upgrade)
            economy_priorities.update(strategy.morph_overlord())
            expansion_boost = self.expansion_boost if self._skip_roach_warren else 0.0
            expansion_priority = self.builder.expansion_priority() + expansion_boost
            economy_priorities[UnitTypeId.HATCHERY] = expansion_priority

            confidence = observation.combat.confidence_global if observation.combat else 0.0
            for item, value in economy_priorities.items():
                self._build_priorities[item] = self.economy_priority_transform.transform([value, confidence, 1.0])
            for item, value in army_priorities.items():
                transformed = self.army_priority_transform.transform([value, confidence, 1.0])
                if self.bot.mediator.get_did_enemy_rush:
                    transformed += self.army_priority_boost_vs_rush
                self._build_priorities[item] = transformed
            for item, value in tech_priorities.items():
                self._build_priorities[item] = self.tech_priority_transform.transform([value, confidence, 1.0])

            if expansion_priority > -1 and self.bot.count_planned(UnitTypeId.HATCHERY) == 0:
                self._macro_plans[UnitTypeId.HATCHERY] = MacroPlan()

            tech_composition = dict(strategy.tech_composition)
            if self._skip_roach_warren:
                tech_composition.pop(UnitTypeId.ROACHWARREN, None)

            for unit, count in tech_composition.items():
                if (
                    self.bot.count_actual(unit) + self.bot.count_pending(unit) < count
                    and not any(self.bot.get_missing_requirements(unit))
                    and self.bot.count_planned(unit) == 0
                ):
                    self._macro_plans[unit] = MacroPlan(priority=-0.5)

            self._macro_plans.update(strategy.make_spines())
            self._macro_plans.update(strategy.make_spores())

        self._build_priorities = {
            item: priority
            for item, priority in self._build_priorities.items()
            if not any(self.bot.get_missing_requirements(item))
        }

    def get_actions(self) -> Mapping[Unit, Action]:
        return self._actions
