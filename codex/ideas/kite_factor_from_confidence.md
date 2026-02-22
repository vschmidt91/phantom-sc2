# Kiting

don't always kite.
add a factor (0=full retreat, 1=full kite).
learned transform from local (and global?) confidence.

## Core idea

Replace binary "kite / don't kite" with a continuous control value:

`kite_factor in [0, 1]`

- `0.0`: pure disengage / maximize distance
- `0.5`: trade while preserving spacing
- `1.0`: aggressive stutter / maintain DPS uptime

## Confidence inputs

Use two confidence channels and fuse them:

- `local_confidence`: nearby fight estimate (current skirmish envelope)
- `global_confidence`: strategic posture (eco, tech, map control, reinforcements)

Candidate features for `local_confidence`:

- nearby allied vs enemy DPS (air/ground split)
- nearby allied vs enemy effective HP
- cooldown/readiness (weapon cooldown, spell energy for key units)
- positional edge (concave, high ground, choke ownership)
- range edge (can we hit while taking low return fire?)

Candidate features for `global_confidence`:

- supply + army value delta
- upgrade delta
- reinforcement ETA delta
- production momentum (active larva/inject/production cycles)
- known tech threat flags (e.g. bane/ruptor/storm windows)

## Transform options

Map confidence to `kite_factor` with one of these:

1. Hand-tuned monotonic curve for bootstrap
2. Small learned calibrator (logistic / tiny MLP)
3. Piecewise lookup table learned from self-play

Simple starting form:

`kite_factor = sigmoid(a * local_confidence + b * global_confidence + c)`

Then clamp with tactical overrides.

## Hard overrides (safety)

Never let learned output violate obvious tactical rules:

- if lethal-incoming in <= N frames -> force retreat (`kite_factor=0`)
- if target is one-shot and safe to finish -> force commit (`kite_factor=1`)
- if unit is in spell danger zone -> bias retreat strongly
- if trapped (poor escape path) -> avoid fake kiting oscillation

## Behavior integration sketch

Use factor as blend between two movement intents:

- `retreat_vector`: maximize survivability
- `dps_vector`: maintain firing solution

`move_vector = lerp(retreat_vector, dps_vector, kite_factor)`

Stability controls:

- temporal smoothing (`ema` on factor)
- hysteresis bands to avoid frame-to-frame flip
- per-unit-class caps (queens/stalkers/marines can use different max aggression)

## Training + data

Bootstrapping plan:

1. Start with scripted confidence score + fixed curve
2. Log combat slices: features, chosen factor, short-horizon outcome
3. Fit calibrator offline to maximize expected value (damage trade, survival, objective hold)
4. Gate rollout per matchup/unit type

Loss candidates:

- weighted sum: survival, net resource trade, objective retention
- optional KL regularization toward scripted baseline for safer early learning

## Evaluation

Track before/after on bot-independent combat scenarios:

- DPS uptime
- own unit survival %
- value traded per second
- disengage success rate
- overkill / target-switch churn

Rollout criteria:

- no regression in defensive survival
- reduced over-retreat in winning local fights
- measurable gain in mid-size skirmish efficiency

## Open questions

- should global confidence affect all units equally, or only frontline?
- should factor be per-unit, per-squad, or both (squad baseline + unit deltas)?
- is map-specific calibration needed for choke-heavy vs open maps?
- how to expose interpretability hooks during replay debugging?
