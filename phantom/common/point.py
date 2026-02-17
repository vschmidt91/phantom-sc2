from collections.abc import Sequence

type Point = tuple[int, int]


def to_point(p: Sequence[float]) -> Point:
    return int(p[0]), int(p[1])
