# Changelog

## [3.9.0] - 2026-02-19
### Added
- `DeadAirspace` reachability checks plus the blocked spire placement fix ensure we only target/place structures that can actually be reached and built, removing wasted air-fire assignments.
- `ScoutProxy` now tracks per-tile vision age and directs second overlords toward long-unseen ground tiles, while overlords gain the creep-drop micro component so they cast creep and position according to the mediator’s assignments.
- The component abstraction now runs per-unit (`get_action(unit)`), concrete fields replace abstract component loops in `Agent`, and the unified tactics registry handles age-ranked task forces, keeping prioritization intact.
- Worker pathing, own-creep flood fill, and ZvZ creep-hull throttling mellow risky movements: builders and transfer drones follow safe paths, retreat logic only uses connected creep, and creep spread in ZvZ sticks inside the convex hull of controlled bases.
