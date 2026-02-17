# PLAN

# Status

- completed

## Objective

Implement a `DeadAirspace` component that prevents combat target selection when a flying target is outside pathing-constrained attack reach, and integrate it into agent setup and combat target filtering.

## Scope

- Build a new manager/component under the existing micro/manager architecture.
- Precompute reachability maps for air attack ranges `0..20` using convolution on pathable terrain.
- Add a runtime API to validate whether attacker `A` can realistically target flying unit `B`.
- Wire the component through agent initialization and per-step combat flow.
- Update combat targeting logic to exclude unreachable air targets.
- Add tests covering algorithm correctness and behavioral integration.

## Implementation Plan

### Phase 1: Locate integration points and conventions

1. Inspect existing manager classes in micro-related modules to mirror construction and lifecycle patterns.
2. Identify where manager components are instantiated with `pathing_grid` in the agent bootstrap.
3. Locate combat component initialization and `fight_with` target-selection path.
4. Confirm available utility functions for:
   - circular kernel generation,
   - convolution or morphology on grids,
   - tile/index conversion for world positions.

Deliverable:
- Clear map of files/classes/functions to modify, with minimal architecture drift.

### Phase 2: Implement `DeadAirspace` component

1. Create a new class `DeadAirspace` (matching existing manager style and naming conventions).
2. Constructor inputs:
   - initial `pathing_grid`,
   - optional config constants for min/max supported range (default `0..20`).
3. Precompute candidate ranges:
   - `candidate_ranges = list(range(0, 21))`.
4. For each range `r`:
   - build a circular kernel of radius `r` on tile coordinates,
   - convolve/dilate pathable mask with the kernel,
   - store resulting boolean grid keyed by `r`, representing shootable tiles.
5. Keep precomputed maps in memory for O(1) lookup at runtime.
6. Add defensive handling for out-of-bounds lookup and unknown/unsupported ranges.

Deliverable:
- New component with precomputed reachability maps for every integer range `0..20`.

### Phase 3: Implement runtime check API

Add method (example signature, adjust to project conventions):
- `can_target(attacker: Unit, target: Unit) -> bool`

Logic:
1. If `attacker.can_attack_air` is false, return `False` immediately.
2. Resolve attacker air weapon range (convert to grid range as needed; clamp/round to integer map key policy).
3. Resolve target position to tile index.
4. Read precomputed convolved grid for attacker range.
5. Return whether target tile is marked reachable.
6. If data missing (no range map or invalid position), fail safe with `False`.

Range policy (explicitly implement and document):
- Prefer floor/round/clamp consistently so runtime lookup always maps to `0..20`.
- If actual range exceeds 20, clamp to 20 unless future requirement expands precompute size.

Deliverable:
- Stable API for combat code to evaluate air target reachability.

### Phase 4: Wire into agent lifecycle

1. Instantiate `DeadAirspace` together with other manager components in agent setup.
2. Pass initial `pathing_grid` from existing source used by other map-aware managers.
3. Ensure component is available in per-step flow (`on_step`) where combat component is built/updated.
4. Inject/pass `DeadAirspace` into combat component constructor or method call path.

Deliverable:
- `DeadAirspace` available to combat logic every frame.

### Phase 5: Integrate into combat target selection

1. In `combat.fight_with`, identify branch where potential targets are filtered/scored.
2. Apply dead-airspace check for flying targets:
   - if target is flying, require `dead_airspace.can_target(attacker, target) == True`,
   - otherwise keep existing ground-target behavior unchanged.
3. Preserve any existing target-priority logic; only exclude unreachable candidates.
4. Ensure behavior when `dead_airspace` is unavailable is deterministic (prefer explicit fallback).

Deliverable:
- Combat will not choose unreachable flying targets.

### Phase 6: Testing and validation

Unit tests:
1. Kernel/convolution correctness on small synthetic grids for select ranges (`0`, `1`, `5`, `20`).
2. `can_target` early return when `can_attack_air` is false.
3. `can_target` returns false for out-of-bounds/unsupported range.
4. Range mapping policy tests (round/clamp behavior).

Integration/behavior tests:
1. Scenario where flying target is near but behind unpathable dead-air gap:
   - previously targetable by pure distance,
   - now excluded by dead-airspace check.
2. Scenario where reachable flying target remains selectable.
3. Regression check that non-flying target selection is unchanged.

Performance checks:
1. Measure one-time precompute cost on startup.
2. Confirm per-frame lookup cost is constant and low.

Deliverable:
- Tests proving correctness and no major regressions.

## File-Level Change Checklist

- Add new component file for `DeadAirspace` in the micro/manager area.
- Update exports/import wiring if package init files require registration.
- Update agent initialization file to instantiate and retain the component.
- Update combat component/module to accept and use `DeadAirspace`.
- Add/adjust tests in existing test suites for manager/combat behavior.

## Risk Register and Mitigations

1. Coordinate mismatch (world position vs tile index):
   - Mitigation: reuse existing map conversion helpers already used by pathing modules.
2. Incorrect range quantization:
   - Mitigation: centralize quantization in one helper and test boundary values.
3. Convolution performance or memory overhead:
   - Mitigation: precompute once, store compact boolean arrays, avoid per-frame recompute.
4. Behavioral regression in combat target priorities:
   - Mitigation: apply check as candidate exclusion only, keep existing scoring untouched.

## Acceptance Criteria

1. `DeadAirspace` exists and precomputes shootable-tile maps for all integer ranges `0..20`.
2. `can_target(attacker, target)` returns false when attacker cannot attack air.
3. Combat `fight_with` excludes flying targets that fail dead-airspace reachability.
4. Component is created from agent with initial `pathing_grid` and available in on-step combat flow.
5. Tests cover core algorithm and combat integration paths and pass.

## Suggested Execution Order

1. Add `DeadAirspace` skeleton + precompute.
2. Add `can_target` API + tests for isolated behavior.
3. Wire agent initialization + dependency injection into combat.
4. Integrate `fight_with` filtering logic.
5. Run full tests and tune edge-case handling.
