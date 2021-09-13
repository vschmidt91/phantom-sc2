
# from typing import List

# class Reserve(object):

#     def __init__(self, minerals: int = 0, vespene: int = 0, food: int = 0, trainers: List[int] = [], items: List[str] = []):
#         self.minerals = minerals
#         self.vespene = vespene
#         self.food = food
#         self.trainers = trainers
#         self.items = items

#     def __add__(self, other):
#         return self.__class__(self.minerals + other.minerals, self.vespene + other.vespene, self.food + other.food, self.trainers + other.trainers, self.items + other.items)

#     def __repr__(self) -> str:
#         return f"Reserve({self.minerals}M, {self.vespene}G, {self.food}F, {self.trainers}, {self.items})"
