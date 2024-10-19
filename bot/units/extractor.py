from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.unit import Unit, UnitCommand

from ..behaviors.extractor_trick import ExtractorTrickBehavior

if TYPE_CHECKING:
    from ..ai_base import PhantomBot


class Extractor(ExtractorTrickBehavior):
    def __init__(self, ai: PhantomBot, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return self.do_extractor_trick()
