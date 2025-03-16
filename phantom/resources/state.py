from phantom.resources.action import ResourceAction
from phantom.resources.observation import HarvesterAssignment, ResourceObservation


class ResourceState:
    assignment = HarvesterAssignment({})
    gather_hash = 0

    def step(self, observation: ResourceObservation) -> ResourceAction:
        action = ResourceAction(observation, self.assignment, self.gather_hash)
        self.assignment = action.harvester_assignment
        self.gather_hash = observation.gather_hash
        return action
