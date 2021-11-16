
from typing import Dict, Set, Tuple, List

import numpy as np

class BinnedMap(object):

    def __init__(self, size, num_bins):
        self.size: np.ndarray = np.array(size)
        self.num_bins = num_bins
        self.bins: List[List[Set]] = [[
                set()
                for x in range(num_bins)
            ]
            for y in range(num_bins)
        ]

    def clear(self):
        for row in self.bins:
            for bin in row:
                bin.clear()

    def add(self, item, position):
        position = np.asarray(position)
