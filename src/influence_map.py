
from __future__ import annotations
from typing import TYPE_CHECKING
from scipy.ndimage import gaussian_filter

import numpy as np
from skimage.draw import disk

if TYPE_CHECKING:
    from .ai_base import AIBase

class InfluenceMap:

    def __init__(self, data):
        self.data = data
        
    @staticmethod
    def zeros(shape) -> 'InfluenceMap':
        data = np.zeros(shape)
        return InfluenceMap(data)

    def add(self, position: np.ndarray, radius: float, value):
        d = disk(position, radius, shape=self.data.shape)
        self.data[d[0], d[1], :] += value

    def clear(self, value = 0.0) -> None:
        self.data[:, :, :] = value

    def blur(self, sigma: float) -> None:
        for i in range(self.data.shape[2]):
            self.data[:,:,i] = gaussian_filter(self.data[:,:,i], sigma)

    def __getitem__(self, key) -> np.ndarray:
        key = np.asarray(key).astype(int)
        return self.data[key[0], key[1], :]

    def __setitem__(self, key, value) -> np.ndarray:
        key = np.asarray(key).astype(int)
        self.data[key[0], key[1], :] = value