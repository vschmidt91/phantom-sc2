from dataclasses import dataclass, field
from typing import Iterable, Protocol

from .action import Action
from .base import BotBase


class ChatContext(Protocol):

    async def chat_send(self, message: str, team_only: bool) -> None:
        """"""


@dataclass
class ChatAction(Action):
    message: str
    team_only: bool

    async def execute(self, bot: BotBase) -> bool:
        await bot.client.chat_send(self.message, self.team_only)
        return True

    def __hash__(self) -> int:
        return hash(self.message)


@dataclass
class Chat:
    _unsent_messages: set[ChatAction] = field(default_factory=set)
    _sent_messages: set[ChatAction] = field(default_factory=set)

    def do_chat(self) -> Iterable[Action]:
        for message in list(self._unsent_messages):
            yield message
            self._unsent_messages.remove(message)
            self._sent_messages.add(message)

    def add_message(self, message: str, team_only: bool = False) -> None:
        action = ChatAction(message, team_only)
        if action not in self._sent_messages | self._unsent_messages:
            self._unsent_messages.add(action)

    def add_tag(self, tag: str) -> None:
        message = f"Tag:{tag}"
        self.add_message(message, True)
