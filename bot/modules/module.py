from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ai_base import AIBase


class AIModule:

    def __init__(self, ai: AIBase) -> None:
        self.ai = ai

    async def on_step(self) -> None:
        pass
