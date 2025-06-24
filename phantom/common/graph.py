from collections import defaultdict
from collections.abc import Hashable, Sequence, Set

import numpy as np
from scipy.linalg import null_space


def graph_components(adjacency_matrix: np.ndarray) -> Set[Sequence[int]]:
    assert adjacency_matrix.ndim == 2
    assert adjacency_matrix.shape[0] == adjacency_matrix.shape[1]
    adjacency_matrix.shape[0]

    degrees = np.sum(adjacency_matrix, axis=0)
    laplacian = np.diag(degrees) - adjacency_matrix
    kernel_basis = null_space(laplacian)

    components_dict = defaultdict[Hashable, list[int]](list)
    for i, eigencoords in enumerate(kernel_basis):
        key = tuple(round(x, 8) for x in eigencoords)
        components_dict[key].append(i)

    compositions_set = set(map(tuple, components_dict.values()))
    return compositions_set
