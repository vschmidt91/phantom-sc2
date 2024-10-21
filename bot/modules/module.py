from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from action import Action

if TYPE_CHECKING:
    from ..ai_base import PhantomBot


class AIModule:
    def __init__(self, ai: PhantomBot) -> None:
        self.ai = ai

    def on_step(self) -> Iterable[Action]:
        pass
