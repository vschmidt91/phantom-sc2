# Reduced Creep Spread with Convex Hull

The bot is going absolutely ham on creep spread which is awesome.
However, in ZvZ creep also benefits the opponent.
Top level play only connects the townhalls. This is what we want.

## Implemented Approach

1. `Agent` owns a persistent `scipy.spatial.ConvexHull` with `incremental=True`.
2. Hull initialization uses three anchors:
   - `start_location`
   - `mediator.get_own_nat`
   - `mediator.get_defensive_third`
3. For each anchor, 10 ring candidate points are generated at radius 10.
4. On every completed hatchery, another 10 ring candidate points are added through incremental hull updates.
5. Candidate points are append-only for the entire game; they are never removed.
6. Hull membership is used as creep target filter in ZvZ / Random.

## Notes

- use scipy ConvexHull
- early return if enemy_race not in {Race.Zerg, Race.Random}
- no periodic hull rebuild and no creep-edge sampling path

## efficient hull membership test

```py
hull = ConvexHull(points, incremental=True)
hull.add_points(new_points)

def points_in_hull(points, hull, tol=1e-12):
    A = hull.equations[:, :2]
    b = hull.equations[:, 2]
    return np.all(points @ A.T + b <= tol, axis=1)
```
