import logging
import lzma
import math
import pickle
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sc2.ids.unit_typeid import UnitTypeId
from sc2_helper.combat_simulator import CombatSimulator
from tqdm import tqdm

from phantom.micro.simulator import ModelCombatSetup, NumpyLanchesterSimulator, SimulationUnit
from phantom.mock.combat_setups import positions_for_setup, setup_cases
from phantom.mock.hp_ratio_sim import predict_outcome as hp_ratio_predict_outcome

logger = logging.getLogger(__name__)
DEFAULT_DATASET_PATH = "resources/combat_sim/mock.pkl.xz"

# sc2-helper enum values from resources/sc2-helper-master/src/enums.rs
ATTRIBUTE_LIGHT = 1
ATTRIBUTE_ARMORED = 2
ATTRIBUTE_BIOLOGICAL = 3
ATTRIBUTE_MECHANICAL = 4
ATTRIBUTE_PSIONIC = 6

WEAPON_GROUND = 1
WEAPON_AIR = 2


@dataclass(frozen=True)
class UnitSpec:
    unit_type: UnitTypeId
    health: float
    shield: float
    armor: float
    radius: float
    speed: float
    is_flying: bool
    attributes: tuple[int, ...]
    cost_minerals: int
    cost_vespene: int
    ground_weapon: dict | None
    air_weapon: dict | None


@dataclass
class MockCost:
    minerals: int
    vespene: int
    time: float


@dataclass
class MockTypeData:
    attributes: list[int]
    cost: MockCost


@dataclass
class MockWeapon:
    type: int
    damage: float
    attacks: int
    range: float
    speed: float
    damage_bonus: list | None = None


class MockUnit:
    def __init__(self, spec: UnitSpec, tag: int, is_enemy: bool, position: tuple[float, float]) -> None:
        self.type_id = spec.unit_type
        self._type_data = MockTypeData(
            attributes=list(spec.attributes),
            cost=MockCost(minerals=spec.cost_minerals, vespene=spec.cost_vespene, time=1.0),
        )
        self.name = spec.unit_type.name.title()
        self.is_light = ATTRIBUTE_LIGHT in spec.attributes
        self.is_armored = ATTRIBUTE_ARMORED in spec.attributes
        self.is_biological = ATTRIBUTE_BIOLOGICAL in spec.attributes
        self.is_mechanical = ATTRIBUTE_MECHANICAL in spec.attributes
        self.is_massive = False
        self.is_psionic = ATTRIBUTE_PSIONIC in spec.attributes

        weapons: list[MockWeapon] = []
        if spec.ground_weapon:
            weapons.append(MockWeapon(type=WEAPON_GROUND, **spec.ground_weapon))
        if spec.air_weapon:
            weapons.append(MockWeapon(type=WEAPON_AIR, **spec.air_weapon))
        self._weapons = weapons

        self.ground_dps = _calculate_dps(spec.ground_weapon)
        self.ground_range = float(spec.ground_weapon["range"]) if spec.ground_weapon else 0.0
        self.air_dps = _calculate_dps(spec.air_weapon)
        self.air_range = float(spec.air_weapon["range"]) if spec.air_weapon else 0.0
        self.armor = spec.armor
        self.movement_speed = spec.speed
        self.health = spec.health
        self.health_max = spec.health
        self.shield = spec.shield
        self.shield_max = spec.shield
        self.energy = 0.0
        self.energy_max = 0.0
        self.radius = spec.radius
        self.is_flying = spec.is_flying
        self.attack_upgrade_level = 0
        self.armor_upgrade_level = 0
        self.shield_upgrade_level = 0

        self.tag = tag
        self.is_enemy = is_enemy
        self.real_speed = spec.speed
        self.position = position


UNIT_SPECS = (
    UnitSpec(
        unit_type=UnitTypeId.ZERGLING,
        health=35.0,
        shield=0.0,
        armor=0.0,
        radius=0.375,
        speed=4.13,
        is_flying=False,
        attributes=(ATTRIBUTE_LIGHT, ATTRIBUTE_BIOLOGICAL),
        cost_minerals=25,
        cost_vespene=0,
        ground_weapon=dict(damage=5.0, attacks=1, range=0.1, speed=0.497),
        air_weapon=None,
    ),
    UnitSpec(
        unit_type=UnitTypeId.ROACH,
        health=145.0,
        shield=0.0,
        armor=1.0,
        radius=0.625,
        speed=3.15,
        is_flying=False,
        attributes=(ATTRIBUTE_ARMORED, ATTRIBUTE_BIOLOGICAL),
        cost_minerals=75,
        cost_vespene=25,
        ground_weapon=dict(damage=16.0, attacks=1, range=4.0, speed=1.43),
        air_weapon=None,
    ),
    UnitSpec(
        unit_type=UnitTypeId.QUEEN,
        health=175.0,
        shield=0.0,
        armor=1.0,
        radius=0.875,
        speed=1.31,
        is_flying=False,
        attributes=(ATTRIBUTE_BIOLOGICAL, ATTRIBUTE_PSIONIC),
        cost_minerals=150,
        cost_vespene=0,
        ground_weapon=dict(damage=8.0, attacks=2, range=5.0, speed=0.71),
        air_weapon=dict(damage=8.0, attacks=2, range=7.0, speed=0.71),
    ),
    UnitSpec(
        unit_type=UnitTypeId.MARINE,
        health=45.0,
        shield=0.0,
        armor=0.0,
        radius=0.375,
        speed=3.15,
        is_flying=False,
        attributes=(ATTRIBUTE_LIGHT, ATTRIBUTE_BIOLOGICAL),
        cost_minerals=50,
        cost_vespene=0,
        ground_weapon=dict(damage=6.0, attacks=1, range=5.0, speed=0.61),
        air_weapon=dict(damage=6.0, attacks=1, range=5.0, speed=0.61),
    ),
    UnitSpec(
        unit_type=UnitTypeId.MARAUDER,
        health=125.0,
        shield=0.0,
        armor=1.0,
        radius=0.5625,
        speed=3.15,
        is_flying=False,
        attributes=(ATTRIBUTE_ARMORED, ATTRIBUTE_BIOLOGICAL),
        cost_minerals=100,
        cost_vespene=25,
        ground_weapon=dict(damage=10.0, attacks=1, range=6.0, speed=1.07),
        air_weapon=None,
    ),
    UnitSpec(
        unit_type=UnitTypeId.HELLION,
        health=90.0,
        shield=0.0,
        armor=0.0,
        radius=0.75,
        speed=5.95,
        is_flying=False,
        attributes=(ATTRIBUTE_LIGHT, ATTRIBUTE_MECHANICAL),
        cost_minerals=100,
        cost_vespene=0,
        ground_weapon=dict(damage=8.0, attacks=1, range=5.0, speed=1.79),
        air_weapon=None,
    ),
    UnitSpec(
        unit_type=UnitTypeId.ZEALOT,
        health=100.0,
        shield=50.0,
        armor=1.0,
        radius=0.5,
        speed=3.15,
        is_flying=False,
        attributes=(ATTRIBUTE_LIGHT, ATTRIBUTE_BIOLOGICAL),
        cost_minerals=100,
        cost_vespene=0,
        ground_weapon=dict(damage=8.0, attacks=2, range=0.1, speed=0.86),
        air_weapon=None,
    ),
    UnitSpec(
        unit_type=UnitTypeId.STALKER,
        health=80.0,
        shield=80.0,
        armor=1.0,
        radius=0.625,
        speed=4.13,
        is_flying=False,
        attributes=(ATTRIBUTE_ARMORED, ATTRIBUTE_MECHANICAL),
        cost_minerals=125,
        cost_vespene=50,
        ground_weapon=dict(damage=13.0, attacks=1, range=6.0, speed=1.34),
        air_weapon=dict(damage=13.0, attacks=1, range=6.0, speed=1.34),
    ),
    UnitSpec(
        unit_type=UnitTypeId.ADEPT,
        health=70.0,
        shield=70.0,
        armor=1.0,
        radius=0.5,
        speed=3.5,
        is_flying=False,
        attributes=(ATTRIBUTE_LIGHT, ATTRIBUTE_BIOLOGICAL),
        cost_minerals=100,
        cost_vespene=25,
        ground_weapon=dict(damage=10.0, attacks=1, range=4.0, speed=1.61),
        air_weapon=None,
    ),
)
UNIT_SPEC_BY_TYPE: dict[UnitTypeId, UnitSpec] = {spec.unit_type: spec for spec in UNIT_SPECS}


def generate_mock_combat_dataset(
    simulation_count: int,
    spawn_count: int,
    use_position: bool,
    seed: int,
) -> list[dict]:
    rng = random.Random(seed)
    sim_true = CombatSimulator()
    sim_true.enable_timing_adjustment(use_position)
    sim_pred = NumpyLanchesterSimulator(_MockLanchesterParameters(), num_steps=10)
    cases = setup_cases()
    own_pool, enemy_pool = _create_unit_type_pool(spawn_count)

    logger.info(
        "Starting setup simulations: simulation_count=%s setup_cases=%s unit_types=%s spawn_count=%s",
        simulation_count,
        len(cases),
        len(UNIT_SPECS),
        spawn_count,
    )

    results: list[dict] = []
    for sample_index in tqdm(range(simulation_count), desc="Combat simulations (mock setups)"):
        case = cases[sample_index % len(cases)]
        army_size = rng.randint(1, min(len(own_pool), len(enemy_pool)) - 1)
        composition1 = _sample_composition(own_pool, army_size, rng)
        composition2 = _sample_composition(enemy_pool, army_size, rng)

        positions1, positions2 = positions_for_setup(case.name, case.parameter_value, army_size, army_size)
        army1 = build_mock_units(composition=composition1, positions=positions1, is_enemy=False, start_tag=1)
        army2 = build_mock_units(composition=composition2, positions=positions2, is_enemy=True, start_tag=100_000)
        all_units = [*army1, *army2]

        winner, health_remaining = sim_true.predict_engage(army1, army2)
        outcome = _outcomes(
            units1=army1,
            units2=army2,
            winner=winner,
            health_remaining=health_remaining,
        )

        model_setup = ModelCombatSetup(
            units1=[to_simulation_unit(unit) for unit in army1],
            units2=[to_simulation_unit(unit) for unit in army2],
            attacking={u.tag for u in all_units},
        )
        pred_outcome = sim_pred.simulate(model_setup).outcome_global
        pred_outcome_hp_ratio = hp_ratio_predict_outcome(army1, army2)

        results.append(
            dict(
                setup=case.name,
                parameter_name=case.parameter_name,
                parameter_value=case.parameter_value,
                units=[_serialize_unit(unit) for unit in all_units],
                true_outcome=outcome["outcome_global"],
                pred_outcome=pred_outcome,
                pred_outcome_hp_ratio=pred_outcome_hp_ratio,
                true_advantage_log=outcome["advantage_log"],
                true_bitterness_log=outcome["bitterness_log"],
            )
        )

    return results


def write_mock_combat_dataset(results: list[dict], dataset_path: str | Path, project_root: Path) -> Path:
    output_path = _resolve_output_path(dataset_path, project_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Writing %s samples to %s", len(results), output_path)
    with lzma.open(output_path, "wb") as file:
        pickle.dump(results, file, protocol=pickle.HIGHEST_PROTOCOL)
    return output_path


def unit_spec(unit_type: UnitTypeId) -> UnitSpec:
    return UNIT_SPEC_BY_TYPE[unit_type]


def build_mock_units(
    composition: Mapping[UnitTypeId, int],
    positions: list[tuple[float, float]],
    is_enemy: bool,
    start_tag: int,
) -> list[MockUnit]:
    total_units = sum(composition.values())
    if total_units != len(positions):
        raise ValueError(f"positions length mismatch: expected {total_units}, got {len(positions)}")

    units: list[MockUnit] = []
    tag = start_tag
    index = 0
    for unit_type, count in composition.items():
        spec = unit_spec(unit_type)
        for _ in range(count):
            units.append(MockUnit(spec=spec, tag=tag, is_enemy=is_enemy, position=positions[index]))
            tag += 1
            index += 1
    return units


def to_simulation_unit(unit: MockUnit) -> SimulationUnit:
    return SimulationUnit(
        tag=unit.tag,
        is_enemy=unit.is_enemy,
        is_flying=unit.is_flying,
        health=unit.health,
        shield=unit.shield,
        ground_dps=unit.ground_dps,
        air_dps=unit.air_dps,
        ground_range=unit.ground_range,
        air_range=unit.air_range,
        radius=unit.radius,
        real_speed=unit.real_speed,
        position=(float(unit.position[0]), float(unit.position[1])),
    )


@dataclass
class _MockLanchesterParameters:
    time_distribution_lambda: float = 1.0
    lancester_dimension: float = 1.5
    enemy_range_bonus: float = 1.0


def _calculate_dps(weapon: dict | None) -> float:
    if not weapon:
        return 0.0
    return float(weapon["damage"] * weapon["attacks"] / weapon["speed"])


def _serialize_unit(unit: MockUnit) -> dict:
    return dict(
        tag=unit.tag,
        is_enemy=unit.is_enemy,
        is_flying=unit.is_flying,
        health=unit.health,
        shield=unit.shield,
        ground_dps=unit.ground_dps,
        air_dps=unit.air_dps,
        ground_range=unit.ground_range,
        air_range=unit.air_range,
        radius=unit.radius,
        real_speed=unit.real_speed,
        position=(float(unit.position[0]), float(unit.position[1])),
    )


def _create_unit_type_pool(spawn_count: int) -> tuple[list[UnitTypeId], list[UnitTypeId]]:
    own: list[UnitTypeId] = []
    enemy: list[UnitTypeId] = []
    for spec in UNIT_SPECS:
        for _ in range(spawn_count):
            own.append(spec.unit_type)
            enemy.append(spec.unit_type)
    return own, enemy


def _sample_composition(pool: list[UnitTypeId], army_size: int, rng: random.Random) -> dict[UnitTypeId, int]:
    return dict(Counter(rng.sample(pool, army_size)))


def _outcomes(
    units1: list[MockUnit],
    units2: list[MockUnit],
    winner: bool,
    health_remaining: float,
) -> dict[str, float]:
    health1 = sum(u.health + u.shield for u in units1)
    health2 = sum(u.health + u.shield for u in units2)
    if health1 <= 0 or health2 <= 0:
        return {"outcome_global": 0.0, "advantage_log": 0.0, "bitterness_log": 0.0}

    outcome_global = health_remaining / health1 if winner else -health_remaining / health2
    casualties1 = 1.0
    casualties2 = 1.0
    if winner:
        casualties1 = (health1 - health_remaining) / health1
    else:
        casualties2 = (health2 - health_remaining) / health2

    advantage_log = 0.0
    bitterness_log = 0.0
    if casualties1 > 0 and casualties2 > 0:
        casualties1_log = math.log(casualties1)
        casualties2_log = math.log(casualties2)
        advantage_log = (casualties2_log - casualties1_log) / 2
        bitterness_log = (casualties2_log + casualties1_log) / 2

    return {
        "outcome_global": float(outcome_global),
        "advantage_log": float(advantage_log),
        "bitterness_log": float(bitterness_log),
    }


def _resolve_output_path(dataset_path: str | Path, project_root: Path) -> Path:
    path = Path(dataset_path)
    if not path.is_absolute():
        return project_root / path
    return path
