from abc import ABC, abstractmethod


class Component[TObservation, TState, TAction](ABC):

    @abstractmethod
    def step(self, observation: TObservation, state: TState) -> tuple[TState, TAction]:
        pass
