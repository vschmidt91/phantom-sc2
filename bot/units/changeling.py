from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.unit import Unit, UnitCommand

from ..behaviors.search import SearchBehavior

if TYPE_CHECKING:
    from ..ai_base import PhantomBot


class Changeling(SearchBehavior):
    def __init__(self, ai: PhantomBot, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return self.search()
