import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.ndimage import gaussian_filter

from phantom.common.action import Action, UseAbility
from phantom.common.constants import ENERGY_COST, HALF
from phantom.common.utils import circle, circle_perimeter, line
from phantom.knowledge import Knowledge
from phantom.observation import Observation

TUMOR_RANGE = 10
_TUMOR_COOLDOWN = 304
_BASE_SIZE = (5, 5)


class CreepState:
    def __init__(self, knowledge: Knowledge) -> None:
        self.knowledge = knowledge
        self.created_at_step = dict[int, int]()
        self.spread_at_step = dict[int, int]()
        self.placement_map = np.zeros(knowledge.map_size)
        self.value_map = np.zeros_like(self.placement_map)
        self.value_map_blurred = np.zeros_like(self.placement_map)

    def _update(self, obs: Observation, mask: np.ndarray) -> None:
        self.placement_map = obs.creep & obs.is_visible & (obs.pathing == 1) & mask
        self.value_map = (~obs.creep & (obs.pathing == 1)).astype(float)
        size = _BASE_SIZE
        for b in self.knowledge.bases:
            i0 = b[0] - size[0] // 2
            j0 = b[1] - size[1] // 2
            i1 = i0 + size[0]
            j1 = j0 + size[1]
            self.placement_map[i0:i1, j0:j1] = False
            self.value_map[i0:i1, j0:j1] *= 3
        self.value_map_blurred = gaussian_filter(self.value_map, 3) * (obs.pathing == 1).astype(float)

    @property
    def unspread_tumor_count(self):
        return len(self.created_at_step) - len(self.spread_at_step)

    def step(self, obs: Observation, mask: np.ndarray) -> "CreepAction":
        if obs.iteration % 10 == 0:
            self._update(obs, mask)

        for t in set(self.created_at_step) - set(self.spread_at_step):
            if (cmd := obs.unit_commands.get(t)) and cmd.exact_id == AbilityId.BUILD_CREEPTUMOR_TUMOR:
                self.spread_at_step[t] = obs.game_loop

        def is_active(t: Unit) -> bool:
            creation_step = self.created_at_step.setdefault(t.tag, obs.game_loop)
            if t.tag in self.spread_at_step:
                return False
            return creation_step + _TUMOR_COOLDOWN <= obs.game_loop

        all_tumors = obs.structures({UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMOR})
        active_tumors = {t for t in all_tumors if is_active(t)}

        return CreepAction(
            self,
            obs,
            mask,
            active_tumors,
        )


class CreepAction:
    def __init__(self, context: CreepState, obs: Observation, mask: np.ndarray, active_tumors: set[Unit]):
        self.context = context
        self.obs = obs
        self.mask = mask
        self.active_tumors = active_tumors

    def _place_tumor(self, unit: Unit, r: int, full_circle=False) -> Action | None:
        x0 = round(unit.position.x)
        y0 = round(unit.position.y)

        circle_fn = circle if full_circle else circle_perimeter
        targets = circle_fn(x0, y0, r, shape=self.obs.creep.shape)
        if not any(targets):
            return None

        target = max(targets, key=lambda t: self.context.value_map_blurred[t])

        if unit.is_structure:
            target = unit.position.towards(Point2(target), TUMOR_RANGE).rounded

        advance = line(target[0], target[1], x0, y0)
        for p in advance:
            if self.context.placement_map[p]:
                target_point = Point2(p).offset(HALF)
                return UseAbility(unit, AbilityId.BUILD_CREEPTUMOR, target_point)

        # logger.warning("No creep tumor placement found.")
        return None

    def spread_with_queen(self, queen: Unit) -> Action | None:
        if ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN] <= queen.energy:
            return self._place_tumor(queen, 12, full_circle=True)
        return None

    def spread_with_tumor(self, tumor: Unit) -> Action | None:
        return self._place_tumor(tumor, 10)
