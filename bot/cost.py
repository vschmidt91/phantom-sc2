from dataclasses import dataclass


@dataclass
class Cost:
    minerals: float
    vespene: float
    food: float
    larva: float

    def __add__(self, other: "Cost"):
        return Cost(
            self.minerals + other.minerals,
            self.vespene + other.vespene,
            self.food + other.food,
            self.larva + other.larva,
        )

    def __sub__(self, other: "Cost"):
        return Cost(
            self.minerals - other.minerals,
            self.vespene - other.vespene,
            self.food - other.food,
            self.larva - other.larva,
        )

    def __mul__(self, factor: float):
        return Cost(self.minerals * factor, self.vespene * factor, self.food * factor, self.larva * factor)

    def __repr__(self) -> str:
        return f"Cost({self.minerals}M, {self.vespene}G, {self.food}F, {self.larva}L)"
