from dataclasses import dataclass

from bot.resources.action import ResourceAction
from bot.resources.observation import HarvesterAssignment, ResourceObservation


@dataclass
class ResourceState:
    assignment: HarvesterAssignment

    def step(self, observation: ResourceObservation) -> ResourceAction:
        action = ResourceAction(observation, self.assignment)
        self.assignment = action.next_assignment
        return action
