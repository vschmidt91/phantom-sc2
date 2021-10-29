
class Cost(object):

    def __init__(self, minerals: int, vespene: int, food: int):
        self.minerals = minerals
        self.vespene = vespene
        self.food = food

    def __add__(self, other):
        return self.__class__(self.minerals + other.minerals, self.vespene + other.vespene, self.food + other.food)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.minerals}M, {self.vespene}G, {self.food}F)"
