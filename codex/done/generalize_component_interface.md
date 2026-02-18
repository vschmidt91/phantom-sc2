# Component Interface Update

Currently, the component abstraction has two methods on_step and get_actions.
This works fine, but forces components to know exactly which units it wants to command.
This should be future proofed to ensure

- the agent can orchestrate more freely
  - example: combat module might not have enough info to decide if workers should help defend
  - often we could provide this information from the outside
  - but the abstraction should be as general as possible
- slight performance optimization
  - example: no need to run combat logic for units that won't fight

Instead, we want to reverse the flow:
- instead of the component returning all actions
- the agent will call the component one unit at a time

on_step

## Task

1. change the Component get_actions method to get_action(self, unit) -> Action | None
   - on_step can remain unchanged
2. convert all agent components to the new interface
   - component can expose "suggested" units that should get actions
   - suggested units should not be part of the protocol (this pattern will be phased out in the future)
   - for now, agent will just take that suggestion
3. the control flow / action precedence must remain the same
4. remove "abstract" component handling in agent.py
   - all components should have their specific type
   - this removes the need for duck typing for the suggested units
   - also give suggested_units a more fitting name, depending on the component

## Implementation

### Goals and non-goals

- Goals
  - Move to unit-scoped `get_action(unit)` for component decisions.
  - Keep strict action precedence parity in `Agent.on_step`.
  - Keep concrete component typing in `Agent` (no abstract/duck-typed component loops).
  - Treat `Component` protocol as preparation only, not the primary orchestration type.
- Non-goals
  - No combat/strategy tuning.
  - No macro priority redesign.
  - No architectural unification of non-component systems.

### Baseline precedence to preserve

Current effective order in `phantom/agent.py`:

1. `macro_planning.get_actions()` seeds `actions`.
2. Harvester safety/gather logic.
3. Changeling search.
4. Precombat component actions.
5. Combat actions for missing combatants.
6. Roach burrow/unburrow/search fallback.
7. Builder actions override prior entries.
8. Cancel actions.
9. Reactive component actions override prior entries.
10. Tactics override prior entries.
11. Queen search fallback fills only missing queens.

This order and overwrite behavior must not change.

### API design

#### 1) `Component` protocol (`phantom/component.py`)

Protocol is minimal and preparatory only:

- `on_step(self, observation: Observation) -> None`
- `get_action(self, unit: Unit) -> Action | None`

Not in protocol:

- Any suggested-units method.
- Any component grouping/orchestration API.

#### 2) Concrete typing in `Agent`

- Remove abstract component collections typed as `tuple[Component, ...]` for orchestration.
- Keep concrete fields and explicit calls, e.g.:
  - `self.corrosive_biles: CorrosiveBile`
  - `self.creep_spread: CreepSpread`
  - `self.queens: Queens`
  - `self.transfuse: Transfuse`
  - `self.overseers: Overseers`
  - `self.overlords: Overlords`
  - `self.dodge: Dodge`
- `Component` protocol remains useful as an interface guard, but agent flow stays concrete.

#### 3) Component-specific candidate methods (non-protocol)

Replace generic `suggested_units` naming with specific selectors per component:

- `CorrosiveBile`: `ravagers_to_micro()`
- `CreepSpread`: `tumors_to_spread()`
- `Queens`: `queens_to_micro()`
- `Transfuse`: `queens_to_transfuse_with()`
- `Overseers`: `overseers_to_micro()`
- `Overlords`: `overlords_to_micro()`
- `Dodge`: `units_to_dodge_with()`

These are concrete-class methods, not protocol members.

### Agent refactor plan (`phantom/agent.py`)

#### 1) Remove abstract component loops

Replace:

- `self.precombat_components` loop
- `self.reactive_components` loop

With explicit per-component application blocks in current precedence positions.

#### 2) Keep per-component explicit apply

Pattern per component:

1. Call `component.on_step(micro_observation)`.
2. Iterate component-specific selector method.
3. Call `component.get_action(unit)`.
4. Merge into `actions` with same overwrite semantics as today.

No `getattr`, no duck typing, no generic component dispatcher.

#### 3) Preserve precedence

- Precombat application remains before combatant action merge.
- Reactive application remains after builder/cancel logic and before tactics.
- Tactics and queen fallback remain in current locations.

### Component migration details

1. `phantom/micro/corrosive_bile.py`
- Keep cache in `on_step`.
- Add `ravagers_to_micro()`.
- Convert `get_actions` -> `get_action` via `bile_with`.

2. `phantom/micro/creep.py` (`CreepSpread`)
- Keep map update in `on_step`.
- Cache active tumors in `on_step`.
- Add `tumors_to_spread()`.
- Convert `get_actions` -> `get_action` via `spread_with`.

3. `phantom/micro/queens.py`
- Move assignment computation to `on_step` cache.
- Add `queens_to_micro()`.
- Convert `get_actions` -> `get_action(queen)`.

4. `phantom/micro/transfuse.py`
- Keep step reset in `on_step`.
- Add `queens_to_transfuse_with()`.
- Convert `get_actions` -> `get_action` via `transfuse_with`.

5. `phantom/micro/overseers.py`
- Compute scout/detection assignment in `on_step`.
- Add `overseers_to_micro()`.
- Convert `get_actions` -> `get_action(overseer)`.

6. `phantom/micro/overlords.py`
- Keep candidate/assignment prep in `on_step`.
- Add `overlords_to_micro()`.
- Convert `get_actions` -> `get_action(overlord)` preserving safety -> creep-enable -> support ordering.

7. `phantom/micro/dodge.py`
- Keep threat prep in `on_step`.
- Add `units_to_dodge_with()`.
- Convert `get_actions` -> `get_action(unit)`.

### Rollout phases

#### Phase 1: Protocol + concrete agent wiring

1. Update `phantom/component.py` to `get_action` API.
2. In `Agent`, replace abstract component tuples with concrete typed fields.
3. Add explicit per-component apply blocks (no generic dispatch).

#### Phase 2: Component conversions

1. Convert all precombat/reactive components to `get_action`.
2. Add component-specific selector names.
3. Remove legacy `get_actions` call sites.

#### Phase 3: Cleanup + validation

1. Remove dead abstraction helpers.
2. Do a final manual consistency pass on precedence and concrete typing.

### Risks and mitigations

1. Risk: behavior drift while moving assignment work.
- Mitigation: compute assignment once in `on_step`, keep `get_action` lightweight.

2. Risk: missed actions from wrong selector set.
- Mitigation: add debug counters per component (selected units vs actions issued).

3. Risk: accidental abstraction reintroduction.
- Mitigation: keep explicit per-component blocks in agent; avoid generic component utility.

### Acceptance criteria

- `Component` protocol is minimal (`on_step`, `get_action`) and preparatory.
- Agent orchestration uses concrete component types and explicit calls.
- No duck typing or abstract component loop remains in `agent.py`.
- Components expose component-specific selector names (not generic `suggested_units`).
- Action precedence matches baseline.

### Implementation checklist

1. Update `phantom/component.py` protocol.
2. Refactor `phantom/agent.py` to concrete component fields and explicit apply flow.
3. Convert:
   - `phantom/micro/corrosive_bile.py`
   - `phantom/micro/creep.py`
   - `phantom/micro/queens.py`
   - `phantom/micro/transfuse.py`
   - `phantom/micro/overseers.py`
   - `phantom/micro/overlords.py`
   - `phantom/micro/dodge.py`
4. Do final code cleanup and remove dead legacy `get_actions` paths.
