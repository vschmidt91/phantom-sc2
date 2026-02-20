# Counters MLP Composition

There is currently a hand-written counter lookup used by macro strategy:

`enemy composition -> our target composition`

The `phantom/counters` package should host the preparation pipeline for replacing this with a tiny learned composition model while keeping deterministic tooling around it.

## Goals

- Create a stable canonical unit/structure feature space.
- Normalize aliases (burrowed/sieged/morphed variants) into canonical keys.
- Extract supervised targets from the existing `UNIT_COUNTER_DICT`.
- Train a tiny MLP to imitate these targets.
- Keep decoding/constraints outside the model.
- Keep this package standalone and not wired into runtime strategy yet.

## Current shape

- `feature_space.py`: canonical key list, alias mapping, vectorization helpers.
- `table.py`: converts legacy counter table rows into `(x, y)` examples.
- `mlp_composition.py`: tiny one-hidden-layer MLP with simple gradient-descent fitting.
- `decoder.py`: maps predicted distributions back to top-k budgeted unit mix.
- `serialization.py`: save/load model parameters as JSON.

## Follow-up

- Add stricter legality/tech gating decode path.
- Expand canonical feature list with replay-derived or game-data snapshots.
- Add shadow-mode comparison against legacy outputs before integration.
