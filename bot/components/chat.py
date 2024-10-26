from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from ..action import Action
from ..base import BotBase


class ChatContext(Protocol):

    async def chat_send(self, message: str, team_only: bool) -> None:
        raise NotImplementedError()


@dataclass
class ChatAction(Action):
    context: ChatContext
    message: ChatMessage

    async def execute(self, bot: BotBase) -> bool:
        await self.context.chat_send(self.message.message, self.message.team_only)
        return True


@dataclass
class ChatMessage:
    message: str
    team_only: bool

    def __hash__(self) -> int:
        return hash(self.message)


@dataclass
class Chat:
    context: ChatContext
    unsent_messages: set[ChatMessage] = field(default_factory=set)
    sent_messages: set[ChatMessage] = field(default_factory=set)

    def do_chat(self) -> Iterable[Action]:
        for message in list(self.unsent_messages):
            yield ChatAction(self.context, message)
            self.unsent_messages.remove(message)
            self.sent_messages.add(message)

    def add_message(self, message: str, team_only: bool = False) -> None:
        chat_message = ChatMessage(message, team_only)
        if chat_message not in self.sent_messages | self.unsent_messages:
            self.unsent_messages.add(chat_message)

    def add_tag(self, tag: str) -> None:
        message = f"Tag:{tag}"
        self.add_message(message, True)
