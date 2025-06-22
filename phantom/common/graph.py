from collections import defaultdict
from collections.abc import Hashable, Sequence, Set

import numpy as np
from scipy.linalg import null_space


def graph_components(adjacency_matrix: np.ndarray) -> Set[Sequence[int]]:
    assert adjacency_matrix.ndim == 2
    assert adjacency_matrix.shape[0] == adjacency_matrix.shape[1]
    adjacency_matrix.shape[0]

    adjacency_matrix = np.maximum(adjacency_matrix, adjacency_matrix.T)
    degrees = np.sum(adjacency_matrix, axis=0)
    laplacian = np.diag(degrees) - adjacency_matrix
    kernel_basis = null_space(laplacian)

    def component_key(c):
        return hash(tuple(round(x, 8) for x in c))

    components = defaultdict[Hashable, list[int]](list)

    for i, eigencoords in enumerate(kernel_basis):
        key = tuple(round(x, 8) for x in eigencoords)
        components[key].append(i)

    return set(map(tuple, components.values()))

    # component_hashes = list(map(component_key, kernel_basis))
    # component_groups = groupby(range(n), lambda i: component_hashes[i])
    # components = {
    #     tuple(list(g))
    #     for k, g in component_groups
    # }

    # components_list = list(map(lambda col: [i for i, ci in enumerate(col) if abs(ci) > 1e-10], kernel_basis.T))
    # components = list(set(tuple(c) for c in components_list))

    # for (i, ci), (j, cj) in product(enumerate(components), enumerate(components)):
    #     if i == j:
    #         continue
    #     if set(ci) & set(cj):
    #         raise Exception()
    # if set().union(*map(set, components)) != set(range(n)):
    #     raise Exception()

    # return components
