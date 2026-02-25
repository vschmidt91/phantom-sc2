# Baysesian Treatment for alive state

Scope is only phantom/micro/simulator.py

the alive flags are binary: 1 initially and 0 once enough pressure is accumulated
however, pressure is only a rough esimate.
alive flags should be replaced by "readiness" which roughly represents probability of being alive.

# Assumptions

- we know units are alive initially
- alive probability should decrease proportionally to accumulated pressure

# Proposal

- key quantity: pressure_rel = accumulated pressure divided by hp0
- readiness is monotonically decreasing w.r.t. pressure_rel
- pressure_rel = 0 implies readiness = 1
- pressure_rel = 1 implies readiness close to 0

# Questions

- is there a fitting theoretical model for this?
- what should be the actual curve? exponential decay?
- are there other places in the simulator that could get this kind of "bayesian treatment"?