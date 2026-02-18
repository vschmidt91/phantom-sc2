# CONTEXT

- first overlord -> straight to enemy natural (already implemented)
- second overlord -> scout for proxies (to be implemented)

# TASK

1. create component `ScoutProxy`
2. keep a map grid of dtype=int storing the latest game_loop that we had vision at each map tile
3. update this grid every step: where we have vision, override with game_loop
4. assign and remember the _scout_proxy_overlord_tag in agent.py, similar to _scout_overlord_tag
5. pass the overlord to the component (but keep a list of scouts, might assign multiple)
6. keep a dictionary mapping (scout tag -> position to scout) and iterate over them to get the actions
7. when scout needs target:
    - do a local search for unscouted tiles outward from its position
    - start from circle radius `ceil(unit.radius + unit.sight_range)` and expand outward
    - have an upper bound of the number of sampled circle tiles (configurable)
    - always prefer never-seen tiles (grid value `-1`) over previously-seen tiles
    - otherwise, use grid value / scouting age as tie breaker, then distance to own natural
8. when we get vision of a target position through any means, unassign
9. otherwise, go scout there (straight move command for now)
10. integrate actions back into agent. order of priority is (stay safe > proxy scout > creep spotting)

# PLAN

## Objective

Implement a `ScoutProxy` micro component that assigns one or more overlords to scout unobserved ground tiles where proxy structures can exist, using a vision-age grid and safe movement priority rules.

## Implementation Plan

### Phase 1: Define component/config/observation interfaces

1. Create `phantom/micro/scout_proxy.py` with a `ScoutProxy` class implementing the `Component` protocol (`on_step`, `get_actions`).
2. Extend `phantom/observation.py` with proxy-scout fields:
   - `scout_proxy_overlord_tags: tuple[int, ...] = ()`
   - keep `scout_overlord_tag` for first-overlord natural scout.
3. Extend `phantom/common/config.py` with tunables used by proxy scouting:
   - `proxy_scout_samples_max`
   - `proxy_scout_enabled` (default `True`)
   - optional `proxy_scout_max_overlords` (default `1`).
4. Add these defaults to config docs/toml examples if this project keeps config samples.

Deliverable:
- Stable API surface for the new component before behavior code is added.

### Phase 2: Build the vision-age grid

1. In `ScoutProxy.__init__`, allocate an `np.ndarray` (dtype `int32`) sized to map tiles (`bot.game_info.map_size` or equivalent grid shape already used by the bot).
2. Initialize values to `-1` (never seen) or `0` consistently; document this choice in code.
3. Build a ground-only scout mask (for example from finite cells in `clean_ground_grid`) and use it to gate target eligibility.
4. Restrict proxy target selection to this ground mask so air-only/unpathable tiles are never assigned.
5. In `on_step`, every iteration:
   - query visibility grid (`bot.state.visibility.data_numpy` or project-standard accessor),
   - where visible, write current `bot.state.game_loop` into the age grid.
6. Keep this update independent of scout ownership so vision by any unit unassigns targets later.

Deliverable:
- A maintained per-tile “last seen at game_loop” grid.

### Phase 3: Track scout assignment state

1. Add agent-level scout-proxy ownership in `phantom/agent.py`:
   - `_scout_proxy_overlord_tags: tuple[int, ...]` or set/list (start with 1 overlord).
2. Add selection logic similar to `_scout_overlord_tag`, but excluding the first dedicated scout overlord.
3. Pass proxy scout tags in `with_micro(...)` so the component can filter controlled units.
4. In `ScoutProxy`, track:
   - `_target_by_scout_tag: dict[int, Point2]`
   - cleanup for dead/missing overlords each step.
5. When a scout target tile becomes visible by any means, remove assignment from `_target_by_scout_tag`.

Deliverable:
- Reliable scout-to-target state with automatic stale cleanup.

### Phase 4: Target acquisition logic

1. Add `_pick_target_for(overlord: Unit) -> Point2 | None` in `ScoutProxy`.
2. Candidate generation strategy:
   - start from a ring around the overlord (`r = ceil(radius + sight_range)`),
   - expand outward one ring at a time,
   - stop after a bounded number of sampled ring tiles.
3. Candidate filtering:
   - discard currently visible tiles,
   - discard tiles that are not in the ground-only scout mask,
   - keep current assignment until it becomes visible/invalid to reduce churn.
4. Candidate scoring:
   - treat unseen (`-1`) as highest priority,
   - otherwise score by scouting age (`current_game_loop - last_seen_game_loop`),
   - tie-break by shortest distance to own natural.

Deliverable:
- Deterministic-enough target selection that prefers oldest/unseen vision tiles.

### Phase 5: Action generation and priority integration

1. In `ScoutProxy.get_actions`, for each controlled overlord:
   - if combat safety override exists (`observation.combat.keep_unit_safe`), do not issue proxy movement action,
   - otherwise move to assigned/new target with `Move(target)`.
2. Wire component in `Agent.__init__` and `reactive_components` ordering so final priority is:
   1. survival/safety (`keep_unit_safe`)
   2. proxy scouting (`ScoutProxy`)
   3. creep spotting (`Overlords` support positioning).
3. Ensure `Overlords` excludes proxy-scout tags from creep-spotter candidates (similar to current first scout exclusion).
4. Prevent command churn:
   - only reissue move if unit is idle, far from target, or target changed significantly.

Deliverable:
- Proxy scout actions integrated without overriding higher-priority safety behavior.

### Phase 6: Tests and verification

1. Add focused tests (new `tests/test_scout_proxy.py`):
   - vision grid updates every step,
   - visible tile writeback stores latest game_loop,
   - target unassigned once tile becomes visible.
2. Add target-selection tests:
   - unseen tiles outrank stale-seen tiles,
   - stale-seen tiles outrank recently-seen tiles,
   - tie-break prefers tile closest to own natural when age matches.
3. Add integration tests or lightweight agent wiring tests:
   - proxy overlord tag assignment does not collide with `_scout_overlord_tag`,
   - `Overlords` does not command proxy scout overlords when assigned.
4. Run project tests and fix regressions in micro action precedence.

Deliverable:
- Confidence that proxy scouting is stable and does not regress existing overlord behavior.

## File-Level Change Checklist

- `phantom/micro/scout_proxy.py` (new component)
- `phantom/agent.py` (assignment, wiring, component order)
- `phantom/observation.py` (new observation field(s))
- `phantom/micro/overlords.py` (exclude proxy scouts from creep-spotter logic)
- `phantom/common/config.py` (+ optional config toml files) for new tunables
- `tests/test_scout_proxy.py` (new)

## Risks and Mitigations

1. Excessive action spam from frequent target changes:
   - Mitigation: retain assignments until visible/invalid; throttle target replacement.
2. Wrong grid coordinate conversion:
   - Mitigation: centralize world->tile conversion with existing `to_point` utilities.
3. Conflicts with existing overlord micro:
   - Mitigation: explicit exclusions by tag and deterministic component ordering.
4. Performance cost from sampling each frame:
   - Mitigation: bounded sample counts, per-step vision updates, reuse assignments.

## Acceptance Criteria

1. A `ScoutProxy` component exists and is wired into `Agent`.
2. Vision-age grid stores latest seen `game_loop` values and updates every step.
3. Proxy scout overlord tag(s) are assigned, persisted, and passed via `Observation`.
4. Scout targets are selected from unscouted/stale tiles and unassigned when revealed.
5. Scout targets are always ground tiles (never air-only/unpathable tiles).
6. Runtime action priority behaves as `stay safe > proxy scout > creep spotting`.
7. New tests cover grid updates, assignment lifecycle, and target-selection behavior.
