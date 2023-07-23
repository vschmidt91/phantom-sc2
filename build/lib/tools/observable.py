from abc import ABC
from typing import Callable, Generic, List, NoReturn, TypeVar


class Event(ABC):
    pass


TEvent = TypeVar("TEvent", bound=Event)
Callback = Callable[[TEvent], NoReturn]


class Observable(Generic[TEvent]):
    def __init__(self) -> None:
        self.callbacks: List[Callback] = list()

    def subscribe(self, callback) -> None:
        self.callbacks.append(callback)

    def unsubscribe(self, callback) -> bool:
        if callback in self.callbacks:
            self.callbacks.remove(callback)
            return True
        else:
            return False

    def __call__(self, event: TEvent) -> None:
        for callback in self.callbacks:
            callback(event)
