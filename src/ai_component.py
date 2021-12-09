from __future__ import annotations
from typing import TYPE_CHECKING
from abc import ABC

if TYPE_CHECKING:
    from .ai_base import AIBase

class AIComponent(ABC):

    def __init__(self, ai: AIBase):
        self.ai = ai