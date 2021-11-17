

import numpy as np

from sc2.unit import Unit
from .utils import *

class ValueMap(object):

    def __init__(self, size: np.ndarray):
        self.size = np.array(size)
        self.ground_vs_ground = np.zeros(self.size)
        self.ground_vs_air = np.zeros(self.size)
        self.air_vs_ground = np.zeros(self.size)
        self.air_vs_air = np.zeros(self.size)

    def add(self, unit: Unit):
        p = unit.position.rounded
        v = unitValue(unit)
        if unit.is_flying:
            if unit.can_attack_air:
                self.air_vs_air[p] += v
            else:
                self.air_vs_ground[p] += v
        else:
            if unit.can_attack_air:
                self.ground_vs_air[p] += v
            else:
                self.ground_vs_ground[p] += v