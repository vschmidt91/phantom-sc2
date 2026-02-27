from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.ndimage import gaussian_filter
from scipy.spatial import ConvexHull

from phantom.common.action import Action, UseAbility
from phantom.common.constants import ENERGY_COST, HALF
from phantom.common.point import Point, to_point
from phantom.common.utils import circle, circle_perimeter, line
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot

BASE_SIZE = (5, 5)


def hull_to_mask(hull, shape, eps=1e-10):
    nx, ny = shape
    eq = hull.equations
    A = eq[:, :2]
    b = eq[:, 2]
    pts = hull.points[hull.vertices]
    mn = np.floor(pts.min(0)).astype(int)
    mx = np.ceil(pts.max(0)).astype(int)
    x0 = max(mn[0], 0)
    y0 = max(mn[1], 0)
    x1 = nx - 1 if mx[0] >= nx else mx[0]
    y1 = ny - 1 if mx[1] >= ny else mx[1]
    m = np.zeros((nx, ny), np.uint8)
    if x1 < x0 or y1 < y0:
        return m
    X, Y = np.meshgrid(np.arange(x0, x1 + 1, dtype=np.float64), np.arange(y0, y1 + 1, dtype=np.float64), indexing="ij")
    P = np.stack((X.ravel(), Y.ravel()), 1)
    inside = np.all((A @ P.T + b[:, None]) <= 1e-12, 0)
    m[x0 : x1 + 1, y0 : y1 + 1] = inside.reshape((x1 - x0 + 1, y1 - y0 + 1))
    return m


def is_inside_hull(point, hull: ConvexHull, eps=1e-10) -> bool:
    A = hull.equations[:, :-1]
    b = hull.equations[:, -1:]
    coordinates = np.asarray(point, dtype=float)
    flags = coordinates @ A.T + b.T <= eps
    return bool(np.all(flags))


class CreepTumors:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self._tumor_created_at = dict[int, int]()
        self._tumor_active_since = dict[int, int]()
        self.tumor_stuck_game_loops = 3000  # remove the tumor if it fails to spread longer than this
        self.tumor_cooldown = 304

    @property
    def unspread_tumor_count(self):
        return len(self._tumor_active_since) + len(self._tumor_created_at)

    @property
    def active_tumors(self) -> Sequence[Unit]:
        return [self.bot.unit_tag_dict[t] for t in self._tumor_active_since]

    def on_tumor_completed(self, tumor: Unit, spread_by_queen: bool) -> None:
        self._tumor_created_at[tumor.tag] = self.bot.state.game_loop

    def on_step(self) -> None:
        game_loop = self.bot.state.game_loop

        for action in self.bot.actions_by_ability[AbilityId.BUILD_CREEPTUMOR_TUMOR]:
            for tag in action.unit_tags:
                # the tumor might already be marked as stuck if the spread order got delayed due to the APM limit
                self._tumor_active_since.pop(tag, None)

        # find tumors becoming active
        for tag, created_at in list(self._tumor_created_at.items()):
            if tag not in self.bot.unit_tag_dict:
                del self._tumor_created_at[tag]
            elif created_at + self.tumor_cooldown <= game_loop:
                del self._tumor_created_at[tag]
                self._tumor_active_since[tag] = game_loop

        active_tumors = list[Unit]()
        for tag, active_since in list(self._tumor_active_since.items()):
            if active_since + self.tumor_stuck_game_loops <= game_loop:
                logger.info(f"tumor with {tag=} failed to spread for {self.tumor_stuck_game_loops} loops")
                del self._tumor_active_since[tag]
            elif tumor := self.bot.unit_tag_dict.get(tag):
                active_tumors.append(tumor)
            else:
                del self._tumor_active_since[tag]


class CreepSpread:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self._placement_map = np.zeros(bot.game_info.map_size)
        self._value_map = np.zeros_like(self._placement_map)
        self.update_interval = 10
        self.defensive_creep_bonus = 0.2
        self._tumors = CreepTumors(bot)
        self._townhall_hull: ConvexHull | None = None
        self._townhall_hull_mask = np.zeros(bot.game_info.map_size)
        self._townhall_hull_hash = 0

    def on_step(self, observation: Observation | None = None) -> None:
        self._update_townhall_hull()
        self._tumors.on_step()
        if self.bot.actual_iteration % self.update_interval == 0:
            self._update_maps()

    @property
    def unspread_tumor_count(self):
        return self._tumors.unspread_tumor_count

    def on_tumor_completed(self, tumor: Unit, spread_by_queen: bool) -> None:
        self._tumors.on_tumor_completed(tumor, spread_by_queen)

    def tumors_to_spread(self) -> Sequence[Unit]:
        return self._tumors.active_tumors

    def get_action(self, unit: Unit) -> Action | None:
        if unit.type_id == UnitTypeId.QUEEN:
            if 10 + ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN] <= unit.energy:
                return self._place_tumor(unit, 12, full_circle=True)
        elif unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            return self._place_tumor(unit, 10)
        return None

    def _candidate_points(self, base_position: Point2, radius: float = 10.0, count: int = 6) -> np.ndarray:
        angles = np.linspace(0.0, 2.0 * np.pi, num=count, endpoint=False)
        offsets = np.column_stack((np.cos(angles), np.sin(angles))) * radius
        base = np.asarray((base_position.x, base_position.y), dtype=float)
        return base + offsets

    def _update_townhall_hull(self) -> None:
        townhalls = self.bot.townhalls
        townhall_hull_hash = hash(frozenset(townhalls.tags))
        if townhall_hull_hash != self._townhall_hull_hash:
            self._townhall_hull_hash = townhall_hull_hash
            points = np.vstack([self._candidate_points(th.position) for th in townhalls])
            self._townhall_hull = ConvexHull(points)
            self._townhall_hull_mask = hull_to_mask(self._townhall_hull, self.bot.game_info.map_size)

    def _update_maps(self) -> None:
        visibility_grid = np.equal(self.bot.state.visibility.data_numpy.T, 2.0)
        creep_grid = self.bot.mediator.get_creep_grid.T == 1
        pathing_grid = self.bot.clean_ground_grid == 1.0
        safety_grid = self.bot.ground_grid == 1.0
        self._placement_map = creep_grid & visibility_grid & safety_grid
        value_map = np.where(~creep_grid & pathing_grid, 1.0, 0.0)
        self._value_map = gaussian_filter(value_map, 3)

    def is_inside_townhall_hull(self, point) -> bool:
        i, j = int(point[0]), int(point[1])
        return bool(self._townhall_hull_mask[i, j])
        # if self._townhall_hull is None:
        #     return False
        # return is_inside_hull(point, self._townhall_hull)

    def _place_tumor(self, unit: Unit, r: int, full_circle=False) -> Action | None:
        x0 = round(unit.position.x)
        y0 = round(unit.position.y)

        circle_fn = circle if full_circle else circle_perimeter
        targets = circle_fn(x0, y0, r, shape=self._placement_map.shape)

        target: Point | None = None
        target_value = -np.inf

        for p in targets:
            is_defensive = self.is_inside_townhall_hull(p)
            q = Point2(p)
            if not self.bot.is_visible(q):
                continue
            if not self.bot.has_creep(q):
                continue
            if not self.bot.in_pathing_grid(q):
                continue
            if not self._placement_map[p]:
                continue
            if self.bot.enemy_race == Race.Zerg and not is_defensive:
                continue
            if any(e.is_blocked_by(p) for e in self.bot.expansions.values()):
                continue
            if not self.bot.mediator.is_position_safe(grid=self.bot.ground_grid, position=q):
                continue
            v = self._value_map[p] + (self.defensive_creep_bonus if is_defensive else 0.0)
            if target_value < v:
                target_value = v
                target = p

        if target is None:
            return None

        if unit.is_structure:
            target = to_point(unit.position.towards(Point2(target), r))

        advance = line(target[0], target[1], x0, y0)
        for p in advance:
            if self._placement_map[p]:
                target_point = Point2(p).offset(HALF)
                return UseAbility(AbilityId.BUILD_CREEPTUMOR, target_point)

        return None
