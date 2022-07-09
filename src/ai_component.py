from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai_base import AIBase


class AIComponent:

    def __init__(self, ai: AIBase):
        self.ai = ai
