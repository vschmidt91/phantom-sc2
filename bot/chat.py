from dataclasses import dataclass, field
from typing import Iterable

from loguru import logger

from .action import Action
from .base import BotBase


@dataclass
class ChatAction(Action):
    message: str
    team_only: bool

    async def execute(self, bot: BotBase) -> bool:
        logger.info(self.message)
        await bot.client.chat_send(self.message, self.team_only)
        return True

    def __hash__(self) -> int:
        return hash(self.message)


@dataclass
class Chat:
    _unsent: set[ChatAction] = field(default_factory=set)
    _sent: set[ChatAction] = field(default_factory=set)

    def do_chat(self) -> Iterable[Action]:
        for message in list(self._unsent):
            yield message
            self._unsent.remove(message)
            self._sent.add(message)

    def add_message(self, message: str, team_only: bool = False) -> None:
        action = ChatAction(message, team_only)
        if action not in self._sent | self._unsent:
            self._unsent.add(action)

    def add_tag(self, tag: str) -> None:
        message = f"Tag:{tag}"
        self.add_message(message, True)
