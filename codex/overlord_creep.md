# CONTEXT

- except for the initial overlord scout, overlords currently get no commands (except when retreating to safety)
- this should be improved

# STATUS

- brainstorm

# TASK

1. setup an overlord micro component and wire it to the main agent (compare other components)
2. migrate existing overlord micro to that component (currently just retreat when threatened)
3. overlords should spread creep whenever possible
    - check ares for the exact ability to use
    - trigger as overlords pops (if we have lair or hive finished)
    - trigger as lair finishes
4. overlords should advance to aid creep spread (they can see behind blockers and up to high ground terrain)
    - ares provides an optimal positioning to help creep spread
    - use common/distribute.py to optimally spread out overlords to those positions
    - use reverse assignment (position -> overlord) so every position gets at most one overlord assigned
    - use pairwise distance as assignment cost
    - persist assignment over time and reduce assignment cost to 0.0 when already assigned (for stickiness, change other uses of distribution logic)