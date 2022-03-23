from __future__ import annotations
from typing import TYPE_CHECKING
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase
    
class AIModule(AIComponent):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

    async def on_step(self) -> None:                    
        pass