# Blocked Spire

We are losing some games because we fail to build a spire.
Probably also with other tech buildings, let's assume it's a general bug

# Tasks

1. find the placement search function and use python-sc2 placement query (find_placement) instead of ares

# Implementation Plan

1. Keep structure placement search in `Builder._get_structure_target` as random near-base sampling.
2. Replace Ares placement queries with python-sc2 single-point query `await self.bot.can_place_single(...)`.
3. Propagate async only where needed:
   - `Builder.get_actions`
   - `Builder._get_target`
   - `Builder._get_structure_target`
   - `Agent.on_step`
   - `PhantomBot.on_step` callsite (`await self.agent.on_step(...)`)
4. Keep expansion placement logic unchanged to minimize risk.
5. Validate with Python compilation check.

# Execution Status

- [x] Plan written
- [x] Placement checks switched to python-sc2 `can_place_single`
- [x] Minimal async chain propagated
- [x] Python compilation check
