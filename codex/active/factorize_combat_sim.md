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
