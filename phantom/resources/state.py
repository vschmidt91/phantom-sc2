from dataclasses import dataclass, field

from phantom.knowledge import Knowledge
from phantom.resources.action import ResourceAction
from phantom.resources.observation import HarvesterAssignment, ResourceObservation


@dataclass
class ResourceState:
    knowledge: Knowledge
    assignment: HarvesterAssignment = field(default_factory=HarvesterAssignment)
    gather_hash = 0

    def step(self, observation: ResourceObservation) -> ResourceAction:
        action = ResourceAction(self.knowledge, observation, self.assignment, self.gather_hash)
        self.assignment = action.harvester_assignment
        self.gather_hash = observation.gather_hash
        return action
