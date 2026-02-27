# Better time stepping

the time stepping combat simulator works really well.
for each pair unit units i, j we have the time tau_ij until they are in firing contact.
these tau values should be used for discrete firing transport.

# Approaches

1. create exponential distribution with same mean as actual tau
2. use a sampled subset (using all n^2 values is too slow and they are very clustered anyway).

Approach 1 works well and the exponential CDF also used for weighting.
Approach 2 can be mixed in (set union) using same weighting.

# Questions

1. For Approach 2: how to sample the tau values "optimally"?