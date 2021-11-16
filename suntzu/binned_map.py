
from typing import Dict, Set, Tuple, List, TypeVar, Generic, Iterable

import numpy as np

T = TypeVar('T')

class BinnedMap(Generic[T]):

    def __init__(self, size, shape):
        self.size: np.ndarray = np.array(size, dtype=np.float)
        self.shape: np.ndarray = np.array(shape, dtype=np.int)
        self.bins: List[List[Set[T]]] = [[
                set()
                for y in range(self.shape[1])
            ]
            for x in range(self.shape[0])
        ]

    def clear(self):
        for row in self.bins:
            for bin in row:
                bin.clear()

    def add(self, item: T, position):
        position = np.asarray(position)
        index = position / self.size * self.shape
        index = self.position_to_index(position)
        bin = self.bins[index[0]][index[1]]
        bin.add(item)

    def position_to_index(self, position):
        position = np.asarray(position)
        index = position / self.size * self.shape
        index = index.astype(np.int)
        index = np.clip(index, 0, self.shape)
        return index

    def enumerate(self, position_from, position_to) -> Iterable[T]:
        index_from = self.position_to_index(position_from)
        index_to = self.position_to_index(position_to)
        for i in range(index_from[0], index_to[0]):
            for j in range(index_from[1], index_to[1]):
                bin = self.bins[i][j]
                for item in bin:
                    yield item