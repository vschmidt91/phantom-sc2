# Combat Sim divided and conquered

The mechanism of combat is
- damage being dealt from one unit to another.
- neighbouring units covering each other with overlapping fields of fire
- units can move: our units always kite, only question is where to go

That is, we view the battlefield from the bottom up.
Top down is already provided by sc2helper.
The current lanchester simulation reads

    potential = sum(fire) * sum(forces) * sum(count) ** (lancester_pow - 2)
    outcome = potential1 - potential2

which is a principled way to merge battles characterized by three scalars.
initialization for a single unit is

- force = hp + shield
- fire = dps
- count = 1

we want to split the problem up into:

1. Contact esimation: Who can shoot at what?
    - exact at t=0
    - need to model movement for t>0 (current linear growth? brownian motion? move towards modelled targets?)
    - how to store? matrix of probabilities / markov chain?
2. Implement combat sim as matrix operations
   - current approach should not be far off, but reason about this.
   - agree or disagree: the matrix multiplication calculates the expected enemy lanchester potential "received" by a unit
   - would like a similar definition for nearby friendly potential, but whats the best way?
3. Implementation Alternative: the hybrid
   - use sc2helper combat sim for subgroups derived from contact graph
   - use connected components: whenever units are estimated to be in contact, they are simulated together
   - this kind of mixes concerns though, as sc2helper also does time stepping

# Implementation Notes

- this is math, use short variables and write equation-like
- we have CPU cycles to spare
- matrices can stay dense
- not convinced by sparse representation, ask before going there
- I'd rather have a bunch of zero edges but shorted code
- time to contact model makes sense, offload to helper
- okay to assume uniform target selection. focus fire can be modelled later.
- pressure is the right formulation: we want to make this more like discrete ODE stepping
- leave out support term or additional considerations like that for later
- hunting for a principled approximation 
- dont sweat backwards compatibility, no need to keep from the simulator except whats protocol
- e.g. the attacking flags should probably go unless we find an elegant way to inject them.
- (they indicate unit state - confidence has margin, only available for own units)

# Opinion

What is your high level view?
What parts make sense, which do not?

High-level: the factorization is correct, but the order of complexity should be reversed.
The biggest error source in our bad ranges is not the Lanchester aggregation itself, it is contact timing and contact structure.
So "who can shoot when" must be first-class, and only then should we apply Lanchester-style transport.

What makes sense:
- Bottom-up view (damage transport on contact graph) is the right abstraction for extending beyond HP ratios.
- Keeping matrix operations is good for speed and differentiability/parameter fitting.
- Decomposing into contact estimation + attrition is the right split.

What does not (yet) make sense:
- A fully probabilistic Markov/Brownian contact model is likely overkill now; too many knobs, weak identifiability.
- Pure all-to-all expected target mixing washes out local geometry (exactly where we fail now).
- Hybrid "connected components + full sc2helper per component" is useful for analysis/oracle checks, but not ideal as runtime core because it mixes models and can be unstable with component churn.

Agreement on current matrix view:
- Yes: current multiplication is interpretable as expected enemy potential received by each unit.
- Missing piece: a symmetric friendly-support term should not be additive "free power"; it should modulate survival/effective fire through local superiority (e.g., pressure ratio), otherwise we double-count force.

On the claim "`offense` already computes active edges":
- I agree, with an important caveat.
- In `simulator.py`, `valid = alive & in_range_projection & (dps>0)` defines a time-indexed bipartite contact mask.
- `offense` is then a row-normalized version of that mask, so it is effectively a weighted active-edge matrix (who can currently target whom).
- So conceptually, Stage A contact and Stage B transport are already partially present in the inner loop.

What is still missing even if `offense` is active edges:
- Edge quality is binary + uniform split per attacker (`1/num_targets`), which under-represents focus fire and geometry asymmetry.
- All valid targets are treated exchangeably; local choke/frontline structure is blurred.
- The range projection is still a simplified linear envelope, so edge activation timing can be wrong at exactly the problematic setup parameters.

Conclusion:
- The current formulation is not "missing edges"; it is missing edge realism.
- Therefore, I would evolve the existing `offense` path (better edge weights + better activation timing) rather than replacing it wholesale.

# Proposal

What is the most likely to work?

Most likely to work: a 2-stage sparse contact-transport simulator.

Stage A: deterministic contact envelope (cheap, explicit)
- Compute time-to-contact matrix `tau_ij = max(0, (d_ij - r_ij) / v_i_eff)`.
- For each simulation quadrature time `t_k`, activate edge `(i,j)` if `tau_ij <= t_k`.
- Use sparse adjacency only (k-nearest or radius pruned) to preserve local geometry.

Stage B: Lanchester-style transport on active graph
- On active edges, allocate fire with normalized edge weights (range margin + focus prior).
- Compute received pressure per unit from enemy graph only.
- Update effective force/fire by pressure-driven attrition (small explicit step), not one-shot global mixing.
- Aggregate global outcome from final effective force.

Friendly support term (pragmatic)
- Derive local support as friendly pressure nearby, but use it only as:
  - fire retention multiplier (units under less net pressure keep higher effective DPS), or
  - survivability multiplier on attrition rate.
- Avoid direct addition to force to prevent amplification loops.

Parameterization strategy
- Keep few global params plus regime-conditioned gates:
  - `lambda_contact`, `focus_sharpness`, `attrition_gain`, `enemy_range_bonus`.
  - Gate by setup features (`distance`, spread, surround index, line overlap).
- This is simpler than full stochastic motion and should directly address failures at circle/square/crossing_t mid-range values.

Validation plan
- Keep sc2helper as truth.
- Report by setup/parameter with scatter + R2 curves.
- Add ablation sequence:
  1. current model
  2. + deterministic `tau_ij`
  3. + sparse graph
  4. + support-modulated attrition
- Stop when marginal gain flattens; do not overfit with many new parameters.

# Final Report

Implemented a prototype rewrite of `NumpyLanchesterSimulator.simulate` in `phantom/micro/simulator.py`.

What changed:
- Replaced the prior potential/mix post-processing loop with dense discrete time stepping on HP.
- Introduced deterministic time-to-contact per directed edge:
  - `tau_ij = max(0, (d_ij - r_ij) / v_i)` with `inf` for non-targetable edges.
- At each sampled time:
  - active edges are `alive_i * alive_j * (tau_ij <= t) * targetable_ij`,
  - offense is row-normalized active edges (uniform target selection),
  - incoming pressure is aggregated and applied as `hp <- hp - dt * pressure_in`.
- Kept Lanchester exponent influence through attacker strength scaling:
  - `strength_i = (hp_i / hp0_i)^(p-1)` (clamped numerically).
- Removed reliance on the previous `potential1/potential2` and casualty-log transform.

Outputs:
- `outcome_global` is now side survival difference:
  - `mean(survival_own) - mean(survival_enemy)`.
- `outcome_local` remains per-unit and sign-consistent for local attack/disengage gating.

Notes vs implementation guidance:
- Dense matrices retained.
- Uniform target selection retained.
- Contact timing moved into explicit helper math inside the simulator loop (`tau`).
- No support-term added yet (intentionally deferred).
- Existing `attacking` flag support is still honored as a speed gate for now.

Status:
- Prototype compiles and passes project checks.
- Existing simulator unit tests pass after rewrite.
