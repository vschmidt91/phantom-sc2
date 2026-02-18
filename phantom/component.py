from __future__ import annotations

from typing import Protocol

from sc2.unit import Unit

from phantom.common.action import Action
from phantom.observation import Observation


class Component(Protocol):
    def on_step(self, observation: Observation) -> None: ...

    def get_action(self, unit: Unit) -> Action | None: ...
