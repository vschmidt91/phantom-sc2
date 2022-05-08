from __future__ import annotations

from typing import TYPE_CHECKING, Set
import random

from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase
    
class Chat(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.messages: Set[str] = set()

    async def on_step(self) -> None:
        pass

    async def add_message(self, message: str, team_only: bool = False) -> None:
        if message not in self.messages:
            await self.ai.client.chat_send(message, team_only)
            self.messages.add(message)

    async def add_tag(self, tag: str, include_time: bool = True) -> None:
        if include_time:
            message = f'Tag:{tag}@{self.time_formatted}'
        else:
            message = f'Tag:{tag}'
        await self.add_message(message, True)