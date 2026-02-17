# CONTEXT

- except for the initial overlord scout, overlords currently get no commands (except when retreating to safety)
- this should be improved

# STATUS

- done

# TASK

1. setup an overlord micro component and wire it to the main agent (compare other components)
2. migrate existing overlord micro to that component (currently just retreat when threatened)
3. overlords should spread creep whenever possible
    - check ares for the exact ability to use
    - trigger as overlords pops (if we have lair or hive finished)
    - trigger as lair finishes
4. overlords should advance to aid creep spread (they can see behind blockers and up to high ground terrain)
    - ares provides an optimal positioning to help creep spread
    - use `mediator.get_overlord_creep_spotter_positions(overlords=...)` directly
    - ares already returns an assignment dictionary (`overlord_tag -> position`)
    - keep local assignment logic out of the bot unless ares behavior changes

# DETAILED PLAN

## 1) Create and wire an `OverlordMicro` component

1. Add a dedicated component module for overlord behavior (matching existing micro component patterns in the codebase).
2. Define a single public update entrypoint called once per frame from the main agent loop.
3. Inject required dependencies (mediator/interfaces for unit queries, map info, abilities, and pathing) instead of direct global lookups.
4. Register the component in agent initialization with clear ownership of:
   - threat retreat behavior
   - creep-drop behavior
   - positioning for creep support

## 2) Migrate existing retreat logic into the component

1. Move the current "retreat when threatened" logic from its current location into `OverlordMicro`.
2. Preserve behavior parity first (no functional change during migration).
3. Add a thin compatibility shim only if needed, then remove old callsites.
4. Add a regression test or scenario assertion verifying:
   - threatened overlords still retreat
   - non-threatened overlords are not interrupted

## 3) Implement creep-spread ability usage

1. Confirm the exact ares ability id and constraints for overlord creep deployment.
2. Build eligibility checks:
   - unit is an overlord variant capable of creep drop
   - ability off cooldown and affordable
   - not currently in a conflicting command state
3. Add tech-state gating:
   - enabled when lair or hive is completed
   - trigger evaluation when each overlord spawns (post-tech)
   - trigger a one-time sweep when lair finishes to activate idle overlords
4. Add safety checks before casting:
   - avoid casting where creep already exists if wasteful
   - avoid dangerous positions if retreat threshold is exceeded

## 4) Implement proactive overlord positioning for creep support

1. Query ares for overlord creep-spotter assignments each update (or at a throttled cadence):
   - call `mediator.get_overlord_creep_spotter_positions(overlords=...)`
   - consume returned mapping directly as `overlord_tag -> position`
2. Determine candidate overlords:
   - exclude scouting overlord(s) and emergency-retreat units
   - exclude units currently channeling high-priority actions
3. Persist assignment output between refresh intervals:
   - cache assigned position by overlord tag
   - refresh from ares on cadence
   - clear stale entries on death, morph, or missing assignment

## 5) Update shared distribution logic for stickiness (non-overlord usage)

1. Extend distribution helper API to accept:
   - prior assignment mapping
   - optional sticky-cost override callback
2. Keep default behavior unchanged for existing callers.
3. Update any other users that benefit from stickiness only where behavior is desired.
4. Overlord creep-spotter flow should not use local distribute logic while ares already provides assignment.
5. Add tests for:
   - stable assignments across frames when geometry is unchanged
   - reassignment on unit loss / target removal
   - no duplicate overlords assigned to a single target

## 6) Scheduling, priorities, and conflict resolution

1. Define clear action priority for each overlord per frame:
   1. survival retreat
   2. high-value creep-drop cast
   3. movement to assigned creep-support position
   4. idle fallback behavior
2. Ensure command issuance is idempotent to reduce action spam.
3. Use command throttling where appropriate to prevent order churn.

## 7) Observability and tuning

1. Add lightweight debug output / overlays:
   - assigned support positions
   - active creep-drop candidates
   - retreat overrides
2. Add counters/metrics:
   - creep drops attempted / succeeded
   - average assignment lifetime
   - percent of frames with idle eligible overlords
3. Tune thresholds from replay feedback:
   - threat tolerance
   - reassignment decay timing
   - target position refresh cadence

## 8) Validation checklist

1. Unit-level checks for assignment and gating logic.
2. Integration test in bot loop with lair timing transitions.
3. Replay validation on maps with blockers/high ground choke points.
4. Performance check to ensure assignment step does not cause frame spikes.
5. Confirm no regression to initial overlord scout behavior.
