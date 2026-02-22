# Parameter Mapping: exp/logit -> softplus/sigmoid

## Scope

This change centralizes learned-parameter decoding in `phantom/learn/parameters.py` and removes per-module `log`/`logit` decoding logic.

## New API

- `ParameterOptimizer.add_softplus(name, prior, minimum=0.0)`
  - decoded value: `minimum + softplus(raw)`
  - implementation: `minimum + logaddexp(0, raw)`
- `ParameterOptimizer.add_sigmoid(name, prior, low=0.0, high=1.0)`
  - decoded value: `low + (high-low) * sigmoid(raw)`
  - implementation uses stable tanh form: `0.5 * (1 + tanh(0.5 * raw))`

## Migration Summary

### `phantom/micro/simulator.py`

- `time_distribution_lambda_log`: `exp(raw)` -> `softplus(raw)`
- `lancester_dimension_logit`: `1 + sigmoid(raw)` -> `1 + sigmoid(raw)` (same effective mapping via bounded sigmoid `[1, 2]`)
- `enemy_range_bonus_log`: `exp(raw)` -> `softplus(raw)`

### `phantom/macro/mining.py`

- `return_distance_weight_log`: `exp(raw)` -> `softplus(raw)`
- `assignment_cost_log`: `exp(raw)` -> `softplus(raw)`

### `phantom/macro/strategy.py`

- `supply_buffer_log`: `exp(raw)` -> `softplus(raw)`

### `phantom/macro/planning.py`

- `army_priority_boost_vs_rush_log`: `exp(raw)` -> `softplus(raw)`
- `expansion_boost_log`: `exp(raw)` -> `softplus(raw)`

### `phantom/micro/combat.py`

- `global_engagement_hysteresis_log`: `exp(raw)` -> `softplus(raw)`

## Compatibility Note

Parameter registry names were intentionally left unchanged (`*_log`, `*_logit`) to preserve load/save continuity of optimizer state.

## Behavior Impact (Current State)

With priors unchanged, sigmoid-mapped parameters are effectively unchanged.

Softplus-mapped parameters change materially for priors with positive means:

- `mu=2.0`: `exp(mu)=7.389`, `softplus(mu)=2.127`
- `mu=2.5`: `exp(mu)=12.182`, `softplus(mu)=2.579`
- `mu=-3.0`: `exp(mu)=0.050`, `softplus(mu)=0.049` (close)

## Proposed Prior Adjustment (Not Applied)

To preserve the same decoded mean under softplus, approximate by:

- choose new raw mean `mu' = log(exp(target) - 1)`, where `target = exp(old_mu)`
- keep sigma unchanged initially

Concrete candidates:

- `assignment_cost_log`: `Prior(2.0, 1.0)` -> `Prior(7.388, 1.0)`
- `supply_buffer_log`: `Prior(2.5, 0.1)` -> `Prior(12.182, 0.1)`
- `army_priority_boost_vs_rush_log`: `Prior(0.0, 1.0)` -> `Prior(0.541, 1.0)` for matching decoded mean `1.0`
- `expansion_boost_log`: `Prior(log(0.7), 0.1)` -> `Prior(0.014, 0.1)` for mean match
- `time_distribution_lambda_log`: `Prior(-0.5, 0.1)` -> `Prior(-0.181, 0.1)` for mean match
- `enemy_range_bonus_log`: `Prior(0.5, 0.1)` -> `Prior(1.435, 0.1)` for mean match
- `global_engagement_hysteresis_log`: `Prior(-1.62, 0.1)` -> `Prior(-1.519, 0.1)` for mean match
- `return_distance_weight_log`: `Prior(-3.0, 1.0)` -> `Prior(-2.975, 1.0)` (very small change)

Recommendation: apply the prior updates above in one migration commit, then run short training to confirm no instability.
