import math

from bot.resources.context import HarvesterAssignment, ResourceContext
from bot.resources.report import ResourceReport


def update_resources(context: ResourceContext) -> ResourceReport:

    if not context.mineral_fields:
        return ResourceReport(context, HarvesterAssignment({}), 0)

    assignment = context.old_assignment
    assignment = context.update_assignment(assignment)
    gas_target = math.ceil(len(assignment) * context.gas_ratio)
    assignment = context.update_balance(assignment, gas_target)

    return ResourceReport(context, assignment, gas_target)
