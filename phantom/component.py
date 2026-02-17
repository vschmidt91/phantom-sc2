from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from sc2.unit import Unit

from phantom.common.action import Action
from phantom.observation import Observation


class Component(Protocol):
    def on_step(self, observation: Observation) -> None: ...

    def get_actions(self, observation: Observation) -> Mapping[Unit, Action]: ...
