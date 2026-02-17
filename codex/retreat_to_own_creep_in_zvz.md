# CONTEXT

- in ZvP and ZvT, the bot will retreat onto creep when global confidence is low
- for ZvZ this was deactivated because opponent will also spawn creep

# STATUS

- completed

# TASKS

1. implement a component that marks "our" creep as a subset of the creep grid from ares
    - in ZvT/ZvP we can simplify this, all creep is our own
2. check out the "retreat to creep" logic in combat component and use the own creep component

# NOTES

- use common/utils.py/structure_perimeter to get the outline of our own townhalls. ignore creep tumors and overlords for now.
- flood fill the visible creep grid from there
- this might extend onto enemy creep which is fine, we care about creep connectivity from from our townhalls.
- ares or cython_extensions will have flood fill helper
# PLAN

## Objective

Re-enable retreat-on-creep in ZvZ using a simple definition of own creep:
- seed from our townhall perimeters,
- flood fill through visible creep connectivity,
- use that result in combat retreat logic.

## Implementation Plan

### 1) Locate integration points

1. Find where combat currently does "retreat to creep" when global confidence is low.
2. Find where Ares visible creep grid is already available each step.
3. Identify manager/component wiring point to add a lightweight `OwnCreep` helper.

Deliverable:
- Exact files/functions for `OwnCreep` update and retreat-logic consumption.

### 2) Build `OwnCreep` component

1. Add `OwnCreep` component with:
   - `grid` (bool array, same shape as Ares creep grid),
   - `update(...)` method run each frame.
2. ZvT/ZvP rule:
   - `own_creep_grid = visible_creep_grid` (all creep is ours).
3. ZvZ rule:
   - collect our townhalls (hatch/lair/hive),
   - get perimeter seeds using `common/utils.py` `structure_perimeter`,
   - run flood fill on **visible creep tiles only** from those seeds,
   - result is connected creep reachable from our townhalls.
4. Ignore creep tumors/overlords for now.
5. If no seeds exist, return empty own-creep grid.

Deliverable:
- Deterministic per-frame own-creep grid with connectivity semantics.

### 3) Use flood-fill helper

1. Reuse existing flood-fill utility from Ares or `cython_extensions` if available.
2. If helper signatures differ, adapt seed and mask formats at component boundary.
3. Keep operation bounded to map size and current visible creep mask.

Deliverable:
- Fast, robust flood-fill implementation with no custom algorithm duplication.

### 4) Integrate into retreat logic

1. Replace retreat creep predicate with `OwnCreep.grid` / `is_on_own_creep`.
2. Keep low-confidence trigger and retreat scoring logic unchanged.
3. Behavior target:
   - ZvT/ZvP unchanged,
   - ZvZ retreats only to creep connected to our townhalls (even if it later overlaps enemy creep).

Deliverable:
- Combat retreat uses own-creep connectivity in ZvZ.

### 5) Validate with focused tests

1. Unit: ZvT/ZvP mode mirrors visible creep grid.
2. Unit: ZvZ flood fill includes connected creep from townhall perimeter and excludes disconnected islands.
3. Unit: empty-seed case returns empty grid.
4. Integration: low-confidence ZvZ retreat prefers connected own creep, not arbitrary enemy island creep.
5. Regression: ZvT/ZvP retreat behavior unchanged.

Deliverable:
- Coverage for component correctness and retreat behavior.

## Risks

1. Seed coordinate mismatch (world vs tile).
2. Flood-fill helper input expectations may differ.
3. No-townhall edge case early/late game.

## Acceptance Criteria

1. New `OwnCreep` component exists and updates each frame.
2. ZvT/ZvP: all visible creep counts as own creep.
3. ZvZ: own creep is flood-filled visible creep connected to our townhall perimeters.
4. Retreat-to-creep logic uses own creep instead of global creep in ZvZ.
5. Targeted tests pass.
