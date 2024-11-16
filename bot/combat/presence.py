from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Presence:
    dps: np.ndarray
    health: np.ndarray

    def get_force(self, d: np.ndarray | float = 1.5) -> np.ndarray:
        return self.dps * np.power(self.health, d)
