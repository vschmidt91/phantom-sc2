class MetricAccumulator:
    def __init__(self) -> None:
        self.total = 0.0
        self.count = 0.0

    def add_value(self, value: float, weight: float = 1.0) -> None:
        self.total += value
        self.count += weight

    def get_value(self) -> float:
        if self.count == 0.0:
            return 0.0
        return self.total / self.count
