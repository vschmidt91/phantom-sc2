import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CombatSetupCase:
    name: str
    parameter_name: str
    parameter_value: float


DEFAULT_SETUP_PARAMETERS: dict[str, tuple[float, ...]] = {
    "distance": (2.0, 4.0, 6.0, 8.0, 10.0, 12.0),
    "square": (4.0, 6.0, 8.0, 10.0, 12.0),
    "circle": (2.0, 4.0, 6.0, 8.0, 10.0),
    "crossing_t": (4.0, 6.0, 8.0, 10.0, 12.0),
}


def setup_cases(parameters: dict[str, tuple[float, ...]] | None = None) -> list[CombatSetupCase]:
    setup_parameters = parameters or DEFAULT_SETUP_PARAMETERS
    cases: list[CombatSetupCase] = []
    for setup_name, values in setup_parameters.items():
        if setup_name == "distance":
            parameter_name = "distance"
        elif setup_name == "square":
            parameter_name = "size"
        elif setup_name == "circle":
            parameter_name = "radius"
        elif setup_name == "crossing_t":
            parameter_name = "size"
        else:
            raise ValueError(f"unknown setup: {setup_name}")
        cases.extend(
            CombatSetupCase(name=setup_name, parameter_name=parameter_name, parameter_value=float(value))
            for value in values
        )
    return cases


def positions_for_setup(
    setup_name: str, parameter: float, n1: int, n2: int
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    if setup_name == "distance":
        return _distance_positions(distance=parameter, n1=n1, n2=n2)
    if setup_name == "square":
        return _square_positions(size=parameter, n1=n1, n2=n2)
    if setup_name == "circle":
        return _circle_positions(radius=parameter, n1=n1, n2=n2)
    if setup_name == "crossing_t":
        return _crossing_t_positions(size=parameter, n1=n1, n2=n2)
    raise ValueError(f"unknown setup: {setup_name}")


def _distance_positions(
    distance: float, n1: int, n2: int
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    return _grid_around((-distance / 2.0, 0.0), n1), _grid_around((distance / 2.0, 0.0), n2)


def _square_positions(size: float, n1: int, n2: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    y1 = _line_positions(n=n1, span=size)
    y2 = _line_positions(n=n2, span=size)
    x_left = -size / 2.0
    x_right = size / 2.0
    positions1 = [(x_left, y) for y in y1]
    positions2 = [(x_right, y) for y in y2]
    return positions1, positions2


def _circle_positions(radius: float, n1: int, n2: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    positions1: list[tuple[float, float]] = []
    if n1 == 1:
        positions1 = [(radius, 0.0)]
    elif n1 > 1:
        for index in range(n1):
            angle = 2.0 * math.pi * index / n1
            positions1.append((radius * math.cos(angle), radius * math.sin(angle)))
    positions2 = [(0.0, 0.0)] * n2
    return positions1, positions2


def _crossing_t_positions(size: float, n1: int, n2: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    stem_y = _line_positions(n=n1, span=size, start=-size / 2.0, end=size / 2.0)
    bar_x = _line_positions(n=n2, span=size, start=-size / 2.0, end=size / 2.0)
    positions1 = [(0.0, y) for y in stem_y]
    positions2 = [(x, size / 2.0) for x in bar_x]
    return positions1, positions2


def _grid_around(center: tuple[float, float], n: int, spacing: float = 1.5) -> list[tuple[float, float]]:
    if n <= 0:
        return []

    cols = max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    x0, y0 = center
    x_start = x0 - (cols - 1) * spacing / 2.0
    y_start = y0 - (rows - 1) * spacing / 2.0

    positions: list[tuple[float, float]] = []
    for row in range(rows):
        for col in range(cols):
            if len(positions) >= n:
                return positions
            x = x_start + col * spacing
            y = y_start + row * spacing
            positions.append((x, y))
    return positions


def _line_positions(n: int, span: float, start: float | None = None, end: float | None = None) -> list[float]:
    if n <= 0:
        return []
    if n == 1:
        if start is not None and end is not None:
            return [(start + end) / 2.0]
        return [0.0]

    line_start = -span / 2.0 if start is None else start
    line_end = span / 2.0 if end is None else end
    return list(_linspace(line_start, line_end, n))


def _linspace(start: float, end: float, n: int) -> Iterable[float]:
    if n == 1:
        yield start
        return
    step = (end - start) / (n - 1)
    for i in range(n):
        yield start + i * step
