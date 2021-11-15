
from typing import Optional, Set, Union, Iterable, Tuple
import numpy as np

from sc2.position import Point2
from sc2.unit import Unit
from abc import ABC, abstractmethod

class UnitBase(ABC):

    def __init__(self, tag: int):
        self.tag: int = tag

    @abstractmethod
    def micro(self,
        bot,
        enemies: Iterable[Unit],
        friend_map: np.ndarray,
        enemy_map: np.ndarray,
        enemy_gradient_map: np.ndarray,
        dodge: Iterable[Tuple[Point2, float]] = []
    ):
        raise NotImplementedError()