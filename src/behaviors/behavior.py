from __future__ import annotations

from typing import Iterable, Optional, List, TYPE_CHECKING, Callable, Generic, TypeVar, Dict
from sc2.unit import Unit, UnitCommand
from abc import ABC, abstractmethod
from enum import Enum

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Behavior(AIComponent):
    pass