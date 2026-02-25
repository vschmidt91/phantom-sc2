# Parameter switching

We need unique parameter sets per match up: Zerg, Terran, Protoss, Random.
Since behaviour vs random should switch as we find out their race, this needs to be dynamic.

# Tasks

1. Add ParameterContext dataclass holding just enemy_race for now (might be opponent id in the future)
2. Add a middle man between parameter learner and consumers in the agent.

# Notes

- storage should end up in separate files zerg.pkl.xz etc.
- bot.enemy_race is already dynamic, use it to create context on the fly
- training as a passable bool for sampling is perfect, maps directly to our config flag. see if there are other places to do this.
- persistence needs to be split indeed, matchup ratios will never be perfect
- there should be bot.picked_race or similar, use it to train Random + Actual Race.
- no prefix "params_" for filenames, we will make convention: anything in the data folder is a "parameter file" or more generally a learned file. make not of this.

# Implementation plan
1. Define context and policy surface.
   - Add `ParameterContext` in `phantom/learn/parameters.py`:
     - `enemy_race: Race`
   - Add helper:
     - `effective_enemy_race(ctx) -> Race` that maps unknown/`None` to `Race.Random`.
   - Keep this tiny; it is only a selector key for now.

2. Add a parameter provider between learner and consumers.
   - Introduce `MatchupParameterProvider` (or similar) in `phantom/learn/`.
   - Responsibilities:
     - Hold one `ParameterManager` per race key (`Zerg`, `Terran`, `Protoss`, `Random`).
     - Expose a `current(context)` accessor returning the active manager.
     - Expose `load_all()`, `sample_for_game(training: bool)`, `save_result(context, result)`.
   - Consumers should only see a manager-like interface, not file paths or race routing logic.

3. Wire agent construction through the provider.
   - In `phantom/agent.py`, create provider once during init.
   - Build parameterized systems (`CombatSimulatorParameters`, `CombatParameters`, `StrategyParameters`, mining/macro) from `provider.current(context)` instead of a single global manager.
   - Keep a single mutable context in `Agent` and update it when enemy race resolves from `Random` to concrete.

4. Handle dynamic switching vs `Random` safely.
   - Start games vs unknown as `Race.Random`.
   - On first concrete enemy race observation, switch context once:
     - `Random -> Terran|Protoss|Zerg`
   - Do not switch back to `Random` later.
   - Re-log active parameter values at switch time for debugging.

5. Split persistence by matchup.
   - Replace single `params_path` usage with matchup-aware paths:
     - e.g. `params_zerg.pkl.xz`, `params_terran.pkl.xz`, `params_protoss.pkl.xz`, `params_random.pkl.xz`
   - Keep this derived from one base directory/prefix in config, not hardcoded in agent code.
   - `load_all()` should tolerate missing files and initialize empty managers.

6. Keep training updates matchup-specific.
   - In `Agent.on_end`, compute fitness exactly as today.
   - Route `tell(...)` and save to the manager for the *active* context at game end.
   - If opponent stayed unknown all game, train `Random`.

7. Backward compatibility and migration.
   - If legacy single-file params exist, load them into `Random` only (one-time fallback).
   - Log explicit migration message so we can delete fallback later.

8. Validation and rollout.
   - Add tests for:
     - race routing (`Random` default, one-way switch, no flapping),
     - path resolution per matchup,
     - load/save isolation (zerg updates do not affect terran),
     - legacy fallback behavior.
   - Run `make check` after implementation.

# My take
- This is the right direction. A per-matchup optimizer should converge faster than a blended global optimizer because objectives differ materially across ZvZ/ZvT/ZvP.
- The key risk is runtime switching churn during `Random`; solve it with a one-way switch policy and explicit logging.
- I would keep opponent-id personalization out for now; matchup split gives most of the gain for much less complexity.

# Final take
- Implemented with dynamic `.value` routing via a matchup provider + race-bound parameter handles.
- Agent now starts from dynamic enemy race context, switches once from `Random` to concrete race, and logs active parameters on switch.
- Training updates are routed per active matchup, with dual-training (`Random` + resolved race) when opponent selected `Random`.
- Persistence is split into `data/{zerg,terran,protoss,random}.pkl.xz` and legacy single-file fallback is preserved for migration.

# Retrospective: simpler alternative
## Idea
- Keep one `ParameterManager` API and one active manager reference in `Agent`.
- Build all systems against that active manager.
- If race resolves from `Random` to concrete, do not hot-switch internals mid-game.
- Apply the switch only for training/persistence at game end: train `Random`, and optionally also concrete race if discovered.

## Why it is simpler
- No dynamic proxy parameter objects.
- No contextual `.value` indirection layer.
- Fewer types and less typing friction with existing constructor signatures.

## Cost of that simplicity
- No true in-game parameter switch for `Random` games.
- Runtime behavior during `Random` matches stays on `Random` params even after race is known.
- Potentially slower convergence for matchup-specific behavior in mixed ladders.

## Recommendation
- If we optimize for minimum complexity and stability first, this simpler approach is valid.
- If we optimize for maximum per-matchup adaptation quality in-game, the current dynamic `.value` routing is the better fit.
