from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, TypeAlias

from loguru import logger

from .action import Action
from .base import BotBase


@dataclass(frozen=True)
class ChatMessage(Action):
    message: str
    team_only: bool

    async def execute(self, bot: BotBase) -> bool:
        logger.info(self.message)
        await bot.client.chat_send(self.message, self.team_only)
        return True

    def __hash__(self) -> int:
        return hash(self.message)


ChatFunction: TypeAlias = Callable[[ChatMessage], Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class Chat:
    _unsent: set[ChatMessage] = field(default_factory=set)
    _sent: set[ChatMessage] = field(default_factory=set)

    async def do_chat(self, send: ChatFunction):
        for message in list(self._unsent):
            await send(message)
            self._unsent.remove(message)
            self._sent.add(message)

    def add_message(self, message: str, team_only: bool = False) -> None:
        action = ChatMessage(message, team_only)
        if action not in self._sent | self._unsent:
            self._unsent.add(action)
