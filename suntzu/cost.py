
class Cost:

    def __init__(self, minerals: float, vespene: float, food: float):
        self.minerals = minerals
        self.vespene = vespene
        self.food = food

    def __add__(self, other):
        return self.__class__(self.minerals + other.minerals, self.vespene + other.vespene, self.food + other.food)

    def __mul__(self, factor):
        return self.__class__(self.minerals * factor, self.vespene * factor, self.food * factor)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.minerals}M, {self.vespene}G, {self.food}F)"
