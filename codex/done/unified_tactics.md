# Unified Tactics

The first two overlords are currently the only "special task forces" with unique commands.
Let us extend this system more generally.

## Goal

- create a Tactics component
- task forces will be identified by unit type and number:
    - UnitTypeId.OVERLORD, 1
    - UnitTypeId.OVERLORD, 2
    - UnitTypeId.ZERGLING, 1
    - etc
- number is age rank
  - wire unit_created hook from bot into tactics
  - hacky and short is fine
- actual tactics will be a Callable[[Unit], Action | None]
  - add register function
  - once tactics return None, unregister
- on_step matches the unit and tactics
- get_actions executes the tactics and potentially unregisters

## Steering

- make the tactics registry fixed by passing it in the constructor
  - type: Mapping[UnitTypeId, Sequence[Tactic]]
- on_created hook can return early if that type has no tactics
- don't store identities of more units that necessary

## Implementation

1. Add a new `Tactics` component module with a minimal public API:
   - `register(unit_type: UnitTypeId, age_rank: int, tactic: Callable[[Unit], Action | None]) -> None`
   - `on_unit_created(unit: Unit) -> None`
   - `on_step() -> None`
   - `get_actions() -> list[Action]`
2. Store tactics in a dictionary keyed by `(UnitTypeId, age_rank)` and maintain per-type spawn counters to assign age rank in `on_unit_created`.
3. In `on_unit_created`, increment the unit-type counter, compute the new unit's age rank, and map `unit.tag` to its `(unit_type, age_rank)` identity.
4. In `on_step`, resolve currently alive tracked units, match each to a registered tactic via its identity, and prepare an execution list for this frame.
5. In `get_actions`, execute each matched tactic with the current `Unit`:
   - collect returned `Action`s
   - if tactic returns `None`, unregister that tactic key immediately
   - also clean up dead/missing unit tags from tracking state
6. Wire bot lifecycle hooks:
   - call `tactics.on_unit_created(unit)` from the bot's unit-created hook
   - call `tactics.on_step()` in the bot update loop
   - merge `tactics.get_actions()` into the bot's action output pipeline
7. Migrate existing special overlord logic into this registry by registering:
   - `(UnitTypeId.OVERLORD, 1) -> first_overlord_tactic`
   - `(UnitTypeId.OVERLORD, 2) -> second_overlord_tactic`
