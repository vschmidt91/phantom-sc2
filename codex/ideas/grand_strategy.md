# Macro the Micro

- we fight on creep and off creep
- we know how to accumulate battles all the way from single unit to the whole map (t -> inf)
- we will assign offense and defense

## The dance

offense and defense is an assignment problem
can we solve it analytically?

## Target assignment - simulated

- can we use the simulated pressure transport
- and use that in an assignment problem?
- the cost could be (something like) expected casualty surplus
- however, assigning targets in the future does not make sense...
- so probably just momentary contact matrix


## Pathing - solved

- set own structure perimeters as retreat points
- medoid of safe combatants also works great
- for enemy pathing, split into runby and engagement
- creep boundary is the attack set on creep
- creep boundary is the retreat set off creep

## Operational Level

- there is some symmetry there:
  - our and theirs
  - civilian and military targets
- both players assign military to either civilian or military targets (or nothing?)
- can we min-max solve that? need to quantify the value of economy...
- can be seen as risk management: if we don't confront their army, they will hit our eco.
- essentially all of this should be derived from the local and global confidence

## Tactical Level

- not much needed here, our army comp mainly shoots and moves
- overlord drops would be fun
- nydus worms
- german autobahn
- we don't usually go for style points but is nice for watchability

# Opinion

the core direction is correct: macro and micro should be linked by a single confidence-aware assignment layer.
right now the notes already imply this, but the missing piece is a concrete output format that the agent can execute every step.
if we keep the tactical layer simple, we can get most value from better operational decisions without exploding complexity.

# Proposal

define an operational allocator that emits role assignments for each combat cluster:

- roles: `anchor`, `skirmish`, `raid`, `reserve`
- targets: `enemy_army`, `enemy_eco`, `own_army`, `own_eco`
- constraints:
  - keep at least one reserve cluster unless enemy army is fully observed
  - no off-creep commitment below confidence threshold
  - no eco raid if own eco risk exceeds limit

scoring function (cheap approximation):

- objective = expected enemy loss - expected own loss + tempo bonus
- enemy/own loss estimate from local simulation pressure and travel time
- tempo bonus from creep frontier gain and forcing enemy army movement

execution loop:

1. cluster units into current combat groups.
2. compute target scores for each group-role pair.
3. solve assignment greedily with anti-thrash penalty.
4. emit per-group command package with retreat point and timeout.
5. re-evaluate every short interval or on major contact change.

start with one tactical package only (`raid` runby), then add drops/nydus only after measurable gains.

# Open Questions

- how do we calibrate confidence so it is stable across matchups and map sizes?
- which economy value signal is most robust: workers only, mining rate, or base saturation risk?
- should reserve be a hard constraint or a soft penalty when we are ahead?
- what is the minimum reassignment interval that avoids oscillation but still reacts fast enough?
- how do we detect and quantify "enemy army uncertainty" from current scouting data?
- what metrics should gate new tactical packages: winrate delta, damage per supply, or variance reduction?
