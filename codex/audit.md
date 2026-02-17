# Architecture Audit: Agent vs Components

## Guidelines

- create a per-frame context in bot called `Observation`
- create a component protocol with on_step and get_actions
- get_actions should return Mapping[Unit, Action] (components return intentions, which are combined with higher level reasoning)
- event hooks are okay but not favored (makes it hard to track code flow)

## Scope
Reviewed the runtime wiring in `phantom/agent.py`, `phantom/main.py`, and core component modules (`phantom/micro/combat.py`, `phantom/macro/builder.py`, `phantom/macro/strategy.py`, `phantom/macro/mining.py`) with focus on making boundaries between the `Agent` and its components clearer.

## Key Issues

### 1) `Agent` is a god-orchestrator with mixed responsibilities
- `Agent.on_step` currently handles strategic planning, resource policy, mining, combat micromanagement, scouting, cancellation rules, and debug rendering in one method (`phantom/agent.py:104`).
- This centralizes too many policy concerns, making ownership of behavior unclear and changes high-risk.
- Symptom: lifecycle and ordering behavior is encoded as control-flow in one function, not as explicit component contracts.

### 2) Bidirectional and private-state coupling between `PhantomBot` and component internals
- `PhantomBot.count_planned` directly reaches into `self.agent.builder._plans` (`phantom/main.py:307`).
- `PhantomBot._update_tables` also reads `self.agent.builder._plans` (`phantom/main.py:461`).
- `Builder` state is therefore part of bot-level derived tables, but only via private fields, creating brittle hidden coupling.

### 3) Circular dependency through convenience properties
- `Builder` checks `self.bot.blocked_positions` during placement (`phantom/macro/builder.py:161`, `phantom/macro/builder.py:255`).
- `PhantomBot.blocked_positions` delegates to `self.agent.blocked_positions` (`phantom/main.py:335`).
- This creates an implicit cycle (`Agent -> Builder -> Bot -> Agent.blocked_positions`) that is legal but difficult to reason about and easy to break with lifecycle changes.

### 4) Components depend on full `PhantomBot` surface instead of narrow context interfaces
- `Strategy`, `Builder`, `MiningState`, and `CombatState` all take full bot references (`phantom/macro/strategy.py:63`, `phantom/macro/builder.py:51`, `phantom/macro/mining.py:107`, `phantom/micro/combat.py:243`).
- This blurs boundaries between decision logic and game API access, and makes components harder to test, reuse, or evolve independently.

### 5) Action conflict resolution is implicit and order-based
- Final action output is assembled through repeated `actions.update(...)` and per-loop assignments (`phantom/agent.py:139`, `phantom/agent.py:277`, `phantom/agent.py:292`, `phantom/agent.py:315`, `phantom/agent.py:327`).
- The last writer wins, but there is no explicit priority model, no conflict diagnostics, and no clear ownership of command arbitration.

### 6) Bot-owned derived state and component-owned state are interleaved without explicit contracts
- `PhantomBot._update_tables` computes a large mutable shared state used by many components (`phantom/main.py:417`).
- `Agent` and components rely on that precomputed state plus their own internal state each frame, but there is no formal frame context contract ensuring consistency or explaining required update order.

### 7) `CombatStepContext` mixes domain decisions with environment reads and pathing construction
- `CombatStepContext` computes retreat/attack targets and path maps directly via `state.bot` and mediator accessors (`phantom/micro/combat.py:93`, `phantom/micro/combat.py:152`, `phantom/micro/combat.py:199`).
- This makes combat policy hard to isolate from map/query mechanics and increases coupling to bot internals.

## Potential Improvements

### A) Add `Observation` as the only per-frame input surface
- Create `Observation` in `PhantomBot` immediately after `_update_tables`.
- Put all frame-variant read data in it (counts, safety/pathing views, economy snapshot, known units, blocked positions, planned structures).
- Pass `Observation` to agent/components instead of sharing broad `PhantomBot` state for reads.

### B) Standardize component protocol
- Define one protocol for components:
  - `on_step(observation: Observation) -> None`
  - `get_actions(observation: Observation) -> Mapping[Unit, Action]`
- Keep components intention-oriented: they propose actions, agent merges them with higher-level reasoning.
- Avoid adding `prepare`/`propose_intent` variants that create multiple lifecycle shapes.

### C) Minimize event-hook-driven logic
- Keep event hooks only for state that cannot be recovered cheaply from `Observation`.
- Prefer polling from `Observation` in `on_step` over distributed event mutation.
- Move current event-driven component updates behind `on_step` where possible to keep control flow linear.

### D) Remove private cross-object access
- Replace `_plans` reads from `PhantomBot` with explicit `Builder`/planner read APIs (planned counts and planned placements).
- Ensure `PhantomBot` never reaches into component private fields.
- Keep planner ownership inside macro layer; expose only typed read models.

### E) Make action merge deterministic and explicit
- Merge `Mapping[Unit, Action]` from components in one place in `Agent`.
- Document merge order and override rules (for example: safety-critical overrides > combat > macro utility moves).
- Add lightweight collision logging to make overrides observable.

### F) Decompose `Agent.on_step` into staged orchestration
- Keep `Agent` as coordinator with explicit stages: build `Observation`, run component `on_step`, collect `get_actions`, merge, apply agent-level overrides.
- Split large inline policy blocks (macro planning, mining assignment, scouting, unit-special micro) into dedicated components following the same protocol.

## Suggested Refactor Sequence (Low-Risk)
1. Introduce `Observation` in `PhantomBot` and thread it into `Agent.on_step` without changing behavior.
2. Add the component protocol (`on_step`, `get_actions`) and adapt one pilot component (recommend `MiningState`).
3. Replace private planner access (`_plans`) with explicit planner read APIs and update `count_planned`/table code.
4. Migrate remaining components (`Strategy`, `Builder`, `CombatState`, scout/micro helpers) to consume `Observation`.
5. Centralize action merge in agent with documented precedence and collision logs.
6. Collapse non-essential event-hook flows into `on_step` polling to make frame control flow easier to follow.

## Expected Outcome
If applied, these changes will make the agent/component boundary explicit around `Observation` + `on_step/get_actions`, reduce hidden coupling, and make per-frame behavior easier to reason about because control flow remains linear and visible in one orchestration path.
