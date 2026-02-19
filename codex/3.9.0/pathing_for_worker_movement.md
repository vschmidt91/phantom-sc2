# Pathing for Worker Movement

Our drones are getting killed on their way to build hatcheries.
Also drones getting transfered walk in a straight line, although they do keep safe.
We need proper pathing for that.

# Notes

- The required code is already there
  - use our own patched grids in bot.ground_grid, .air_grid
  - ares has A* pathing available (we have cy_dijkstra, but don't use that, it's for multi source)
- premove should be in the builder component
- No tests. I will review. Just go freely.

# Tasks

1. implement helper function in main.py if necessary
2. use in builder component and cancel the task the worker is not safe
3. also for worker to resource pathing

# Implementation

1. Add a worker-safe pathing helper in `main.py`:
   - Input: `start`, `target`, and an optional movement profile (`ground` default).
   - Use `bot.ground_grid` for drones/workers and `bot.air_grid` only where explicitly needed.
   - Run A* via the existing Ares pathing API and return waypoints (or `None` when unreachable).
   - Include a small safety check for each waypoint (grid weight / danger threshold) so callers can abort early.

2. Integrate helper into builder movement logic:
   - Replace direct move-to-target behavior for hatchery builder drones with path waypoints.
   - Before issuing each movement command, verify the next waypoint remains safe.
   - If the path is missing or unsafe, cancel the active build task and release/reassign the worker.
   - Keep existing build assignment and reservation logic intact.

3. Integrate helper into worker transfer / resource movement:
   - Use the same helper for worker-to-resource travel when workers are transferred.
   - Prevent straight-line movement when a safer route exists.
   - Fallback behavior: if no safe path exists, keep worker idle briefly or pick nearest safe intermediate position.

4. Logging and diagnostics (lightweight):
   - Log when builder tasks are canceled due to unsafe pathing.
   - Log when transfer workers switch to safe-waypoint routing.
   - Keep logs concise to avoid spam.

5. Validation pass:
   - Confirm hatchery builders no longer take exposed direct routes.
   - Confirm transferred workers path around dangerous zones.
   - Confirm unsafe path cases cancel cleanly without orphaned reservations.
