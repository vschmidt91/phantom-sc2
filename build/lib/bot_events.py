from dataclasses import dataclass

from sc2.bot_ai import Unit

from src.tools.observable import Event, Observable


@dataclass
class InitEvent(Event):
    pass


@dataclass
class StartEvent(Event):
    pass


@dataclass
class UnitCreatedEvent(Event):
    unit: Unit


@dataclass
class BotEvents:
    on_init = Observable[InitEvent]()
    on_start = Observable[StartEvent]()
    on_unit_created = Observable[UnitCreatedEvent]()
