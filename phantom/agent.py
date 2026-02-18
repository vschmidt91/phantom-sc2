import lzma
import math
import pickle
import random
from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from ares.consts import TOWNHALL_TYPES
from cython_extensions import cy_closest_to, cy_distance_to
from loguru import logger
from sc2.data import Race, Result
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.blocked_positions import BlockedPositionTracker
from phantom.common.config import BotConfig
from phantom.common.constants import (
    CHANGELINGS,
    GAS_BY_RACE,
    RESULT_TO_FITNESS,
)
from phantom.common.metrics import MetricAccumulator
from phantom.common.point import to_point
from phantom.common.utils import calculate_cost_efficiency
from phantom.component import Component
from phantom.learn.parameters import OptimizationTarget, ParameterManager
from phantom.macro.build_order import BUILD_ORDERS
from phantom.macro.builder import Builder, MacroPlan
from phantom.macro.mining import MiningState
from phantom.macro.planning import MacroPlanning
from phantom.macro.strategy import StrategyParameters
from phantom.micro.combat import CombatParameters, CombatState, CombatStep
from phantom.micro.corrosive_bile import CorrosiveBile
from phantom.micro.creep import CreepSpread, CreepTumors
from phantom.micro.dead_airspace import DeadAirspace
from phantom.micro.dodge import Dodge
from phantom.micro.overlords import Overlords
from phantom.micro.overseers import Overseers
from phantom.micro.own_creep import OwnCreep
from phantom.micro.queens import Queens
from phantom.micro.scout_proxy import ScoutProxy
from phantom.micro.simulator import CombatSimulator, CombatSimulatorParameters
from phantom.micro.tactics import Tactics, Until
from phantom.micro.transfuse import Transfuse
from phantom.observation import Observation, with_micro

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class Agent:
    def __init__(self, bot: "PhantomBot", config: BotConfig) -> None:
        self.bot = bot
        self.config = config
        self.optimizer = ParameterManager(config.optimizer_pop_size)
        build_order = BUILD_ORDERS[self.config.build_order]
        dead_airspace = DeadAirspace(self.bot.clean_ground_grid == 1.0)
        simulator = CombatSimulator(bot, CombatSimulatorParameters(self.optimizer))
        self.own_creep = OwnCreep(bot)
        self.combat = CombatState(
            bot,
            CombatParameters(self.optimizer),
            simulator,
            self.own_creep,
            dead_airspace,
        )
        self.builder = Builder(bot)
        self.creep_tumors = CreepTumors(bot)
        self.creep_spread = CreepSpread(bot)
        corrosive_biles = CorrosiveBile(bot)
        dodge = Dodge(bot)
        self.scout_proxy = ScoutProxy(
            bot,
            samples_max=config.proxy_scout_samples_max,
        )
        overlords = Overlords(bot)
        overseers = Overseers(bot)
        self.tactics = Tactics(bot)
        for unit_type, tactic in (
            (UnitTypeId.OVERLORD, self._send_overlord_scout),
            (UnitTypeId.OVERLORD, self.scout_proxy),
            (UnitTypeId.ZERGLING, Until(3 * 60, self.scout_proxy)),
            (UnitTypeId.ZERGLING, Until(3 * 60, self.scout_proxy)),
        ):
            self.tactics.register(unit_type, tactic)
        self.blocked_positions = BlockedPositionTracker(bot)
        queens = Queens(bot, self.creep_spread)
        transfuse = Transfuse(bot)
        strategy_parameters = StrategyParameters(self.optimizer)
        self.macro_planning = MacroPlanning(
            bot=bot,
            params=self.optimizer,
            strategy_parameters=strategy_parameters,
            builder=self.builder,
            build_order=build_order,
        )
        self.mining = MiningState(bot, self.optimizer)
        self.precombat_components: tuple[Component, ...] = (corrosive_biles,)
        self.reactive_components: tuple[Component, ...] = (
            self.creep_spread,
            queens,
            transfuse,
            overseers,
            overlords,
            dodge,
        )
        self.supply_efficiency = MetricAccumulator()
        self._enemy_expanded = False
        self._proxy_structures: list[Unit] = []
        self._skip_roach_warren = False
        for unit in self.bot.units:
            self.tactics.on_unit_created(unit)
        self._load_parameters()
        self._log_parameters()

    def on_step(self, observation: Observation) -> Mapping[Unit, Action]:
        combatants = observation.combatants
        harvester_return_targets = observation.harvester_return_targets

        supply_efficiency = 1 - self.bot.supply_left if self.bot.supply_left > 0 else -24
        self.supply_efficiency.add_value(supply_efficiency)

        if self.bot.time < 5 * 60 or self.bot.townhalls.amount < 3:
            self._proxy_structures = [s for s in self.bot.enemy_structures if self._detect_proxy_structure(s)]
        else:
            self._proxy_structures = []

        self.own_creep.on_step()
        self.combat.on_step(observation)
        combat = self.combat.step
        if combat is None:
            return {}

        macro_observation = with_micro(observation, combat=combat)
        self.macro_planning.set_skip_roach_warren(self._skip_roach_warren)
        self.macro_planning.on_step(macro_observation)
        strategy = self.macro_planning.strategy
        if strategy is None:
            return {}

        actions = dict[Unit, Action]()
        actions.update(self.macro_planning.get_actions())
        build_priorities = dict(self.macro_planning.build_priorities)
        macro_plans = dict(self.macro_planning.macro_plans)

        self.creep_tumors.on_step()
        self.blocked_positions.on_step()
        self.bot.set_blocked_positions(set(self.blocked_positions.blocked_positions))
        detection_targets = tuple(map(Point2, self.blocked_positions.blocked_positions))
        self.tactics.on_step()

        should_inject = self.bot.supply_used + self.bot.bank.larva < 200
        tumor_count = (
            self.creep_tumors.unspread_tumor_count
            + self.bot.count_pending(UnitTypeId.CREEPTUMOR)
            + self.bot.count_pending(UnitTypeId.CREEPTUMORQUEEN)
        )
        tumor_limit = min(3.0 * len(observation.queens), self.bot.time / 30.0)
        should_spread_creep = tumor_count < tumor_limit and self.bot.mediator.get_creep_coverage < 90

        micro_observation = with_micro(
            observation,
            combat=combat,
            should_inject=should_inject,
            should_spread_creep=should_spread_creep,
            detection_targets=detection_targets,
            active_tumors=tuple(self.creep_tumors.active_tumors),
        )
        self.scout_proxy.on_step(micro_observation)
        for component in self.reactive_components:
            component.on_step(micro_observation)
        for component in self.precombat_components:
            component.on_step(micro_observation)

        self.mining.set_context(
            composition_deficit=strategy.composition_deficit,
            planned_cost=self.builder.get_planned_cost(),
            harvesters_exclude=self.builder.assigned_tags | self.bot.pending.keys(),
        )
        self.mining.on_step(observation)

        if not self.bot.researched_speed and self.bot.harvestable_gas_buildings:
            pass
        elif self.bot.townhalls.amount > 1:
            macro_plans.update(self._build_gas(self.mining.gas_target))

        for item, plan in macro_plans.items():
            self.builder.add(item, plan)
        self.builder.on_step()
        resources = self.mining.step_result
        harvesters = self.mining.harvesters
        for harvester in harvesters:
            if not combat.is_unit_safe(
                harvester, weight_safety_limit=6.0
            ) or self.bot.damage_tracker.time_since_last_damage(harvester) < min(self.bot.state.game_loop, 50):
                actions[harvester] = combat.retreat_with(harvester) or combat.move_to_safe_spot(harvester)
            elif resources and (action := resources.gather_with(harvester, harvester_return_targets)):
                actions[harvester] = action

        for changeling in self.bot.units(CHANGELINGS):
            if action := self._search_with(changeling):
                actions[changeling] = action

        for component in self.precombat_components:
            actions.update(component.get_actions(micro_observation))

        combatant_actions = {
            unit: action for unit, action in self.combat.get_actions(observation).items() if unit not in actions
        }
        for combatant in combatants:
            if combatant in actions:
                continue
            if (
                (combatant.type_id == UnitTypeId.ROACH and (action := self._burrow(combatant)))
                or (combatant.type_id == UnitTypeId.ROACHBURROWED and (action := self._unburrow(combatant, combat)))
            ) or (combatant not in combatant_actions and (action := self._search_with(combatant))):
                combatant_actions[combatant] = action

        if self.config.max_actions < len(combatant_actions):
            logger.debug(f"Limiting actions from {len(combatant_actions)} to {self.config.max_actions}")
            selected_keys = list(combatant_actions.keys())
            random.shuffle(selected_keys)
            selected_keys = selected_keys[: self.config.max_actions]
            combatant_actions = {k: combatant_actions[k] for k in selected_keys}
        actions.update(combatant_actions)

        self.builder.set_priorities(build_priorities)
        if self.bot.actual_iteration > 1 or not self.config.skip_first_iteration:
            actions.update(self.builder.get_actions())

        for structure in self.bot.structures.not_ready:
            if structure.health_percentage < 0.05:
                actions[structure] = UseAbility(AbilityId.CANCEL)

        self._maybe_skip_roach_warren()
        if self._skip_roach_warren:
            actions.update(
                {w: UseAbility(AbilityId.CANCEL) for w in self.bot.structures(UnitTypeId.ROACHWARREN).not_ready}
            )

        for component in self.reactive_components:
            actions.update(component.get_actions(micro_observation))
        actions.update(self.tactics.get_actions())

        for queen in observation.queens:
            if queen not in actions and (action := self._search_with(queen)):
                actions[queen] = action

        if self.config.debug_draw:
            self.builder.debug_draw_plans(build_priorities)

        return actions

    def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId) -> None:
        if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            self.creep_tumors.on_tumor_completed(unit, previous_type == UnitTypeId.CREEPTUMORQUEEN)

    def on_unit_created(self, unit: Unit) -> None:
        self.tactics.on_unit_created(unit)

    def on_end(self, game_result: Result):
        if self.config.training:
            cost_efficiency = calculate_cost_efficiency(self.bot.state.score)
            result_value = RESULT_TO_FITNESS[game_result]
            result = {
                OptimizationTarget.CostEfficiency: cost_efficiency + result_value,
                OptimizationTarget.MiningEfficiency: self.mining.efficiency.get_value(),
                OptimizationTarget.SupplyEfficiency: self.supply_efficiency.get_value(),
            }
            logger.info(f"Training parameters with {result=}")
            self.optimizer.tell(result)
            optimizer_state = self.optimizer.save()
            with lzma.open(self.config.params_path, "wb") as f:
                pickle.dump(optimizer_state, f)

    def _send_overlord_scout(self, overlord: Unit) -> Action:
        sight_range = overlord.sight_range
        enemy_nat = self.bot.mediator.get_enemy_nat

        if not self._enemy_expanded:
            enemy_townhalls = self.bot.enemy_structures(TOWNHALL_TYPES)
            expansion_townhalls = [
                th for th in enemy_townhalls if cy_distance_to(th.position, self.bot.enemy_start_locations[0]) > 10
            ]
            if expansion_townhalls:
                self._enemy_expanded = True

        if self._enemy_expanded or self.bot.time >= 140:
            if self.bot.enemy_race in {Race.Zerg, Race.Random}:
                safe_spot = self.bot.mediator.get_enemy_third
            else:
                safe_spot = self.bot.mediator.get_ol_spot_near_enemy_nat
            return Move(safe_spot)

        distance_to_nat = cy_distance_to(overlord.position, enemy_nat)
        if distance_to_nat > sight_range:
            return Move(enemy_nat)
        else:
            if self.bot.enemy_race in {Race.Zerg, Race.Random}:
                safe_spot = self.bot.mediator.get_enemy_third
            else:
                safe_spot = self.bot.mediator.get_ol_spot_near_enemy_nat

            safe_to_nat_distance = cy_distance_to(safe_spot, enemy_nat)
            if safe_to_nat_distance <= sight_range:
                return Move(safe_spot)
            else:
                direction = safe_spot - enemy_nat
                direction_length = cy_distance_to(Point2((0, 0)), direction)
                if direction_length > 0:
                    normalized_direction = direction / direction_length
                    optimal_position = enemy_nat + normalized_direction * sight_range
                    return Move(optimal_position)
                else:
                    return HoldPosition()

    def _load_parameters(self) -> None:
        try:
            with lzma.open(self.config.params_path, "rb") as f:
                optimizer_state = pickle.load(f)
                self.optimizer.load(optimizer_state)
        except Exception as error:
            logger.warning(f"{error=} while loading {self.config.params_path}")

        logger.info("Sampling bot parameters")
        for optimizer in self.optimizer.optimize.values():
            if self.config.training:
                optimizer.set_values_from_latest()
            else:
                optimizer.set_values_from_best()

    def _build_gas(self, gas_harvester_target: int) -> Mapping[UnitTypeId, MacroPlan]:
        gas_type = GAS_BY_RACE[self.bot.race]
        gas_have = (
            len(self.bot.harvestable_gas_buildings)
            + self.bot.count_pending(gas_type)
            + self.bot.count_planned(gas_type)
        )
        gas_max = len(self.bot.all_taken_geysers)
        gas_want = max(1, min(gas_max, math.ceil(gas_harvester_target / self.bot.harvesters_per_gas_building)))
        for _ in range(gas_have, gas_want):
            return {gas_type: MacroPlan()}
        return {}

    def _search_with(self, unit: Unit) -> Action | None:
        if not (unit.is_idle or unit.is_gathering or unit.is_returning):
            return None
        elif self.bot.time < 8 * 60 and self.bot.enemy_start_locations:
            return Move(Point2(random.choice(self.bot.enemy_start_locations)))
        elif self.bot.all_enemy_units:
            target = cy_closest_to(unit.position, self.bot.all_enemy_units)
            return Attack(target.position)
        target = self.bot.random_point(near=unit.position)
        if self.bot.is_visible(target):
            return None
        if self.bot.clean_ground_grid[to_point(target)] == np.inf and not unit.is_flying:
            return None
        return Move(target)

    def _burrow(self, unit: Unit) -> Action | None:
        if (
            UpgradeId.BURROW in self.bot.state.upgrades
            and unit.health_percentage < 0.3
            and not unit.is_revealed
            and unit.weapon_cooldown
            and not self.bot.mediator.get_is_detected(unit=unit, by_enemy=True)
        ):
            return UseAbility(AbilityId.BURROWDOWN)
        else:
            return None

    def _unburrow(self, unit: Unit, combat: CombatStep) -> Action | None:
        if unit.health_percentage > 0.9:
            return UseAbility(AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS in self.bot.state.upgrades and (action := combat.keep_unit_safe(unit)):
            return action
        else:
            return None

    def _log_parameters(self) -> None:
        logger.info(f"{self.combat.simulator.parameters.__dict__=}")
        logger.info(f"{self.combat.parameters.__dict__=}")
        logger.info(f"{self.macro_planning.strategy_parameters.__dict__=}")

    def _detect_proxy_structure(self, structure: Unit) -> bool:
        if structure.is_mine:
            return False

        structure_pos = structure.position
        other_enemy_structures = [s for s in self.bot.enemy_structures if s.tag != structure.tag]

        if other_enemy_structures:
            our_structures = list(self.bot.structures)
            if not our_structures:
                our_structures = [type("MockUnit", (), {"position": self.bot.start_location})()]

            avg_dist_to_ours = sum(cy_distance_to(structure_pos, s.position) for s in our_structures) / len(
                our_structures
            )

            avg_dist_to_theirs = sum(cy_distance_to(structure_pos, s.position) for s in other_enemy_structures) / len(
                other_enemy_structures
            )

            return avg_dist_to_ours < avg_dist_to_theirs
        else:
            if not self.bot.enemy_start_locations:
                return False

            dist_to_our_spawn = cy_distance_to(structure_pos, self.bot.start_location)
            closest_enemy_spawn_dist = min(
                cy_distance_to(structure_pos, enemy_spawn) for enemy_spawn in self.bot.enemy_start_locations
            )

            return dist_to_our_spawn < closest_enemy_spawn_dist

    def _maybe_skip_roach_warren(self) -> None:
        if self.bot.townhalls.amount < 3:
            if self._enemy_expanded and not self.bot.mediator.get_did_enemy_rush and not self._proxy_structures:
                self._skip_roach_warren = True
        else:
            self._skip_roach_warren = False
