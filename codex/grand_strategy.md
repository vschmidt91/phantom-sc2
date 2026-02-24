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

# Q

- how do we calibrate confidence so it is stable across matchups and map sizes?
- which economy value signal is most robust: workers only, mining rate, or base saturation risk?
- should reserve be a hard constraint or a soft penalty when we are ahead?
- what is the minimum reassignment interval that avoids oscillation but still reacts fast enough?
- how do we detect and quantify "enemy army uncertainty" from current scouting data?
- what metrics should gate new tactical packages: winrate delta, damage per supply, or variance reduction?
