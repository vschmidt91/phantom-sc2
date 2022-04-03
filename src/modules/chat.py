from __future__ import annotations

from typing import TYPE_CHECKING, Set
import random

from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

GREET_MESSAGES = [
    "Who dares to challenge me?",
]

FIGHT_MESSAGES = [
    "Chicken. Chicken!",
    "Come on, then.",
    "None shall pass.",
    # "I'll do you for that!",
]

LOSS_MESSAGES = [
    "'tis but a scratch.",
    "Just a flesh wound.",
    "I'M INVINCIBLE!",
    "I've had worse",
    "Alright - we'll call it a draw.",
]

RESPONSES = {
    # "classic": "yes, yes - nothing but Zerglings",
    r"favorite .*?": "The one where the robots dominate",
    r"Now what?": "Oh, had enough, eh?",
    r"gl(\s*)hf": "I move for no bot.",
    r".*": "Then you shall die.",
}
    
class Chat(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

        self.message_greet = random.choice(GREET_MESSAGES)
        self.message_fight = random.choice(FIGHT_MESSAGES)
        self.message_loss = random.choice(LOSS_MESSAGES)
        self.messages: Set[str] = set()
        self.greet_enabled: bool = True

    async def on_step(self) -> None:

        # for item in self.state.chat:
        #     if item.player_id == self.player_id:
        #         continue
        #     for pattern, response in RESPONSES.items():
        #         if match := re.search(pattern, item.message):
        #             await self.add_message(response)
        #             break

        # if 1 < self.ai.time:
        #     if self.ai.opponent_name:
        #         await self.add_message(f'(glhf) {self.ai.opponent_name}')
        #     else:
        #         await self.add_message(f'(glhf)')

        # if 20 < self.time:
        #     await self.add_message(self.message_greet)

        # if 2 * 60 < self.time and 0.5 < self.threat_level:
        #     await self.add_message(self.message_fight)

        # if 4 * 60 < self.time and 0.8 < self.threat_level:
        #     await self.add_message(self.message_loss)

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