import lzma
import math
import pickle
import random
from collections.abc import Mapping, Sequence
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
    CIVILIANS,
    ENEMY_CIVILIANS,
    GAS_BY_RACE,
    RESULT_TO_FITNESS,
)
from phantom.common.cost import Cost
from phantom.common.metrics import MetricAccumulator
from phantom.common.utils import MacroId, calculate_cost_efficiency, to_point
from phantom.learn.parameters import OptimizationTarget, ParameterManager, Prior
from phantom.macro.build_order import BUILD_ORDERS
from phantom.macro.builder import Builder, MacroPlan
from phantom.macro.mining import MiningContext, MiningState
from phantom.macro.strategy import Strategy, StrategyParameters
from phantom.micro.combat import CombatParameters, CombatState, CombatStep
from phantom.micro.corrosive_bile import CorrosiveBile
from phantom.micro.creep import CreepSpread, CreepTumors
from phantom.micro.dead_airspace import DeadAirspace
from phantom.micro.dodge import Dodge
from phantom.micro.overseers import Overseers
from phantom.micro.queens import Queens
from phantom.micro.own_creep import OwnCreep
from phantom.micro.simulator import CombatSimulator, CombatSimulatorParameters

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class Agent:
    def __init__(self, bot: "PhantomBot", config: BotConfig) -> None:
        self.bot = bot
        self.config = config
        self.optimizer = ParameterManager(config.optimizer_pop_size)
        self.build_order = BUILD_ORDERS[self.config.build_order]
        self.dead_airspace = DeadAirspace(self.bot.clean_ground_grid == 1.0)
        self.simulator = CombatSimulator(bot, CombatSimulatorParameters(self.optimizer))
        self.own_creep = OwnCreep(bot)
        self.combat = CombatState(bot, CombatParameters(self.optimizer), self.simulator, self.own_creep)
        self.builder = Builder(bot)
        self.creep_tumors = CreepTumors(bot)
        self.creep_spread = CreepSpread(bot)
        self.corrosive_biles = CorrosiveBile(bot)
        self.dodge = Dodge(bot)
        self.overseers = Overseers(bot)
        self.blocked_positions = BlockedPositionTracker(bot)
        self.queens = Queens(bot)
        self.strategy_paramaters = StrategyParameters(self.optimizer)
        self.mining = MiningState(bot, self.optimizer)
        self.build_order_completed = False
        self.gas_ratio = 0.0
        self.tech_priority_transform = self.optimizer.optimize[OptimizationTarget.CostEfficiency].add_scalar_transform(
            "tech_priority",
            Prior(0.591, 0.1),
            Prior(0.843, 0.1),
            Prior(-0.097, 0.01),
        )
        self.economy_priority_transform = self.optimizer.optimize[
            OptimizationTarget.CostEfficiency
        ].add_scalar_transform("economy_priority", Prior(0.842, 0.1), Prior(0.148, 0.03), Prior(0.039, 0.01))
        self.army_priority_transform = self.optimizer.optimize[OptimizationTarget.CostEfficiency].add_scalar_transform(
            "army_priority", Prior(1.5, 0.1), Prior(0.808, 0.1), Prior(0.5, 0.1)
        )
        self.supply_efficiency = MetricAccumulator()
        self._enemy_expanded = False
        self._scout_overlord_tag: int | None = None
        self._proxy_structures: list[Unit] = []
        self._skip_roach_warren = False
        self.expansion_boost = 0.7
        self._load_parameters()
        self._log_parameters()

    def on_step(self) -> Mapping[Unit, Action]:
        enemy_combatants = self.bot.enemy_units.exclude_type(ENEMY_CIVILIANS)
        combatants = self.bot.units.exclude_type(
            {
                *CIVILIANS,
                UnitTypeId.QUEEN,
                UnitTypeId.QUEENBURROWED,
            }
        )
        queens = self.bot.units(
            {
                UnitTypeId.QUEEN,
                UnitTypeId.QUEENBURROWED,
            }
        )
        overseers = self.bot.units(
            {
                UnitTypeId.OVERSEER,
                UnitTypeId.OVERSEERSIEGEMODE,
            }
        )
        harvester_return_targets = self.bot.townhalls.ready
        strategy = Strategy(self.bot, self.strategy_paramaters)

        supply_efficiency = 1 - self.bot.supply_left if self.bot.supply_left > 0 else -24
        self.supply_efficiency.add_value(supply_efficiency)

        if self.bot.time < 5 * 60 or self.bot.townhalls.amount < 3:
            self._proxy_structures = [s for s in self.bot.enemy_structures if self._detect_proxy_structure(s)]
        else:
            self._proxy_structures = []

        self.own_creep.on_step()
        combat = self.combat.on_step(self.dead_airspace)

        actions = dict[Unit, Action]()
        build_priorities = dict[MacroId, float]()
        macro_plans = dict[UnitTypeId, MacroPlan]()
        if not self.build_order_completed:
            if not self.bot.mediator.is_position_safe(
                grid=self.bot.ground_grid,
                position=self.bot.mediator.get_own_nat,
                weight_safety_limit=10.0,
            ):
                self.build_order_completed = True
            if self.bot.mediator.get_did_enemy_rush:
                self.build_order_completed = True
            if step := self.build_order.execute(self.bot):
                macro_plans.update(step.plans)
                build_priorities.update(step.priorities)
                actions.update(step.actions)
            else:
                logger.info("Build order completed.")
                self.build_order_completed = True
        else:
            # assess priorities
            economy_priorities = self.builder.get_priorities(strategy.macro_composition, limit=1.0)
            army_priorities = self.builder.get_priorities(strategy.army_composition, limit=10.0)
            tech_priorities = self.builder.make_upgrades(strategy.composition_target, strategy.filter_upgrade)
            economy_priorities.update(strategy.morph_overlord())
            expansion_boost = self.expansion_boost if self._skip_roach_warren else 0.0
            expansion_priority = self.builder.expansion_priority() + expansion_boost
            economy_priorities[UnitTypeId.HATCHERY] = expansion_priority

            for k, v in economy_priorities.items():
                build_priorities[k] = self.economy_priority_transform.transform([v, combat.confidence_global, 1.0])
            for k, v in army_priorities.items():
                build_priorities[k] = self.army_priority_transform.transform([v, combat.confidence_global, 1.0])
            for k, v in tech_priorities.items():
                build_priorities[k] = self.tech_priority_transform.transform([v, combat.confidence_global, 1.0])

            # make plans
            if expansion_priority > -1 and self.bot.count_planned(UnitTypeId.HATCHERY) == 0:
                macro_plans[UnitTypeId.HATCHERY] = MacroPlan()
            tech_composition = dict(strategy.tech_composition)
            if self._skip_roach_warren:
                tech_composition.pop(UnitTypeId.ROACHWARREN, None)
            for unit, count in tech_composition.items():
                if (
                    self.bot.count_actual(unit) + self.bot.count_pending(unit) < count
                    and not any(self.bot.get_missing_requirements(unit))
                ) and self.bot.count_planned(unit) == 0:
                    macro_plans[unit] = MacroPlan(priority=-0.5)
            macro_plans.update(strategy.make_spines())
            macro_plans.update(strategy.make_spores())

        # filter out impossible tasks
        build_priorities = {k: v for k, v in build_priorities.items() if not any(self.bot.get_missing_requirements(k))}

        self.creep_tumors.on_step()
        self.creep_spread.on_step()
        self.dodge.on_step()
        self.blocked_positions.on_step()

        def should_harvest_resource(r: Unit) -> bool:
            p = to_point(r.position)
            return self.bot.mediator.is_position_safe(
                grid=self.bot.ground_grid,
                position=self.bot.gather_targets[p],
                weight_safety_limit=6.0,
            )

        required = Cost()
        required += self.builder.get_planned_cost()
        required += self.bot.cost.of_composition(strategy.composition_deficit)
        required -= self.bot.bank
        required = Cost.max(required, Cost())

        if required.minerals == 0 and required.vespene == 0:
            gas_ratio = 0.5
        else:
            gas_ratio = required.vespene / (required.minerals + required.vespene)
        self.gas_ratio = max(0, min(1, gas_ratio))

        harvesters = list[Unit]()
        harvesters_exclude = self.builder.assigned_tags | self.bot.pending.keys()
        harvesters.extend(self.bot.workers.tags_not_in(harvesters_exclude))
        harvesters.extend(self.bot.workers_off_map.values())

        gas_target = math.ceil(len(harvesters) * self.gas_ratio)
        if not self.bot.researched_speed and self.bot.harvestable_gas_buildings:
            gas_target = 2
        elif self.bot.townhalls.amount > 1:
            macro_plans.update(self._build_gas(gas_target))

        for item, plan in macro_plans.items():
            self.builder.add(item, plan)
        self.builder.on_step()

        mineral_fields = [m for m in self.bot.all_taken_minerals if should_harvest_resource(m)]
        gas_buildings = [g for g in self.bot.harvestable_gas_buildings if should_harvest_resource(g)]

        resoure_observation = MiningContext(
            self.bot,
            harvesters,
            mineral_fields,
            gas_buildings,
            gas_target,
        )
        resources = self.mining.step(resoure_observation)

        for harvester in harvesters:
            if not combat.is_unit_safe(
                harvester, weight_safety_limit=6.0
            ) or self.bot.damage_tracker.time_since_last_damage(harvester) < min(self.bot.state.game_loop, 50):
                actions[harvester] = combat.retreat_with(harvester) or combat.move_to_safe_spot(harvester)
            elif action := resources.gather_with(harvester, harvester_return_targets):
                actions[harvester] = action

        for changeling in self.bot.units(CHANGELINGS):
            if action := self._search_with(changeling):
                actions[changeling] = action

        combatant_actions = dict[Unit, Action]()
        for combatant in combatants:
            if (
                (combatant.type_id == UnitTypeId.RAVAGER and (action := self.corrosive_biles.bile_with(combatant)))
                or (combatant.type_id == UnitTypeId.ROACH and (action := self._burrow(combatant)))
                or (combatant.type_id == UnitTypeId.ROACHBURROWED and (action := self._unburrow(combatant, combat)))
                or (action := combat.fight_with(combatant))
                or (action := self._search_with(combatant))
            ):
                combatant_actions[combatant] = action

        if self.config.max_actions < len(combatant_actions):
            logger.debug(f"Limiting actions from {len(combatant_actions)} to {self.config.max_actions}")
            selected_keys = list(combatant_actions.keys())
            random.shuffle(selected_keys)
            selected_keys = selected_keys[: self.config.max_actions]
            combatant_actions = {k: combatant_actions[k] for k in selected_keys}
        actions.update(combatant_actions)

        if self.bot.actual_iteration > 1 or not self.config.skip_first_iteration:
            actions.update(self.builder.get_actions(build_priorities))

        for structure in self.bot.structures.not_ready:
            if structure.health_percentage < 0.05:
                actions[structure] = UseAbility(AbilityId.CANCEL)

        self._maybe_skip_roach_warren()
        if self._skip_roach_warren:
            actions.update(
                {w: UseAbility(AbilityId.CANCEL) for w in self.bot.structures(UnitTypeId.ROACHWARREN).not_ready}
            )

        actions.update(self._micro_queens(queens, combat))

        detection_targets = list(map(Point2, self.blocked_positions.blocked_positions))
        actions.update(
            self.overseers.get_actions(
                overseers=overseers,
                scout_targets=enemy_combatants or self.bot.all_enemy_units,
                detection_targets=detection_targets,
                combat=combat,
            )
        )

        if self._scout_overlord_tag is None:
            overlords = self.bot.units(UnitTypeId.OVERLORD)
            if overlords:
                self._scout_overlord_tag = overlords[0].tag

        if self._scout_overlord_tag is not None:
            scout_overlord = self.bot.unit_tag_dict.get(self._scout_overlord_tag)
            if scout_overlord:
                actions[scout_overlord] = self._send_overlord_scout(scout_overlord)

        for overlord in self.bot.units(UnitTypeId.OVERLORD):
            if overlord.tag != self._scout_overlord_tag and (action := combat.keep_unit_safe(overlord)):
                actions[overlord] = action

        for tumor in self.creep_tumors.active_tumors:
            if action := self.creep_spread.spread_with(tumor):
                actions[tumor] = action

        for unit in self.bot.units:
            if action := self.dodge.dodge_with(unit):
                actions[unit] = action

        if self.config.debug_draw:
            self.builder.debug_draw_plans(build_priorities)

        return actions

    def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId) -> None:
        if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            self.creep_tumors.on_tumor_completed(unit, previous_type == UnitTypeId.CREEPTUMORQUEEN)

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

    def _micro_queens(self, queens: Sequence[Unit], combat: CombatStep) -> Mapping[Unit, Action]:
        should_inject = self.bot.supply_used + self.bot.bank.larva < 200
        tumor_count = (
            self.creep_tumors.unspread_tumor_count
            + self.bot.count_pending(UnitTypeId.CREEPTUMOR)
            + self.bot.count_pending(UnitTypeId.CREEPTUMORQUEEN)
        )
        tumor_limit = min(3.0 * len(queens), self.bot.time / 30.0)
        should_spread_creep = tumor_count < tumor_limit and self.bot.mediator.get_creep_coverage < 90
        actions = self.queens.get_actions(
            queens=queens,
            inject_targets=self.bot.townhalls.ready if should_inject else [],
            creep=self.creep_spread if should_spread_creep else None,
            combat=combat,
        )
        for queen in queens:
            if queen not in actions and (action := self._search_with(queen)):
                actions[queen] = action
        return actions

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
        logger.info(f"{self.simulator.parameters.__dict__=}")
        logger.info(f"{self.combat.parameters.__dict__=}")
        logger.info(f"{self.strategy_paramaters.__dict__=}")

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
