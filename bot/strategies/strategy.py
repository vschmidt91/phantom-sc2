from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterable

from sc2.ids.upgrade_id import UpgradeId

from ..modules.macro import MacroId
from ..modules.module import AIModule

if TYPE_CHECKING:
    from ..ai_base import PhantomBot


class Strategy(ABC, AIModule):
    def __init__(self, ai: PhantomBot):
        super().__init__(ai)

    @abstractmethod
    def update_composition(self) -> None:
        raise NotImplementedError

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        return True
