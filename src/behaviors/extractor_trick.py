from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from ..units.unit import CommandableUnit
from ..constants import *
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class ExtractorTrickBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def do_extractor_trick(self) -> Optional[UnitCommand]:

        if self.unit.type_id != UnitTypeId.EXTRACTOR:
            return None

        if self.unit.is_ready:
            return None

        if not self.ai.extractor_trick_enabled:
            return None

        if 0 < self.ai.supply_left:
            return None

        self.ai.extractor_trick_enabled = False
        return self.unit(AbilityId.CANCEL)
