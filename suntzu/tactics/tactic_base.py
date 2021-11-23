
from abc import ABC, abstractmethod

from typing import Set
import suntzu.common as common

class TacticBase(ABC):

    def __init__(self, bot: common.CommonAI):
        self.bot: common.CommonAI = bot
        self.unit_tags: Set[int] = set()

    @abstractmethod
    def execute(self):
        raise NotImplementedError