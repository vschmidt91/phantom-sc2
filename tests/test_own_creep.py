import numpy as np

from phantom.micro.own_creep import flood_fill_mask


def test_flood_fill_mask_connected_region_only():
    mask = np.zeros((5, 5), dtype=bool)
    mask[1, 1] = True
    mask[1, 2] = True
    mask[2, 2] = True
    mask[4, 4] = True

    filled = flood_fill_mask(mask, [(1, 1)])

    assert filled[1, 1]
    assert filled[1, 2]
    assert filled[2, 2]
    assert not filled[4, 4]


def test_flood_fill_mask_empty_seeds():
    mask = np.ones((3, 3), dtype=bool)

    filled = flood_fill_mask(mask, [])

    assert not filled.any()
