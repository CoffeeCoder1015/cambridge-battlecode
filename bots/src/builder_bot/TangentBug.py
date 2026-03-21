from cambc import Direction, Environment, EntityType, Position
from collections import deque
from heapq import heappush, heappop
from typing import Optional

_ALL_DIRS: list = [d for d in Direction if d != Direction.CENTRE]
_SQRT2: float = 1.4142135623730951
# Reverse-lookup: (dx, dy) -> Direction, built once at import time.
_DELTA_TO_DIR: dict = {d.delta(): d for d in Direction if d != Direction.CENTRE}


class TangentBug:
    """
    Hybrid A* + BugNav2 navigator for builder bots.

    PRIMARY — A* over an accumulated terrain map:
        Every call to next_move() absorbs newly-visible tiles into a local
        Environment cache.  A* uses this cache to plan the shortest known
        path to the target, avoiding confirmed walls.  Unseen tiles are
        treated optimistically as passable; if one turns out to be a wall
        the path is immediately invalidated and replanned.

    FALLBACK — BugNav2 (right-hand boundary following):
        Used when A* exhausts its node budget (no path visible yet) or
        when every direction is blocked in-vision.

    Road placement and actual movement remain the caller's responsibility.

    Usage:
        nav = TangentBug()
        nav.set_target(tx, ty)         # set destination
        direction = nav.next_move(ct)  # call every turn; returns Direction or None
        nav.reset()                    # clear target and all state
    """

    _MAX_ASTAR_NODES: int = 600   # node budget per replan (~0.2 ms margin)
    _REPLAN_EVERY: int = 12       # force replan after this many steps (exploit new tiles)
    _MAX_BOUNDARY_STEPS: int = 256

    def __init__(self) -> None:
        self.target: Optional[tuple[int, int]] = None

        # Accumulated terrain: (x, y) -> Environment for every seen tile.
        self._terrain: dict = {}
        self._map_w: int = 0
        self._map_h: int = 0

        # Cached A* path: deque of Positions from current+1 to goal (inclusive).
        self._path: deque = deque()
        self._steps_since_plan: int = 0

        # Unique counter used as heapq tie-breaker (avoids comparing Positions).
        self._uid: int = 0

        # BugNav2 fallback state.
        self._bug_mode: str = "direct"   # "direct" | "boundary"
        self._hit_dist_sq: int = 0
        self._last_dir: Optional[Direction] = None
        self._boundary_steps: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_target(self, tx: int, ty: int) -> None:
        """Set a new navigation target and reset all internal state."""
        self.target = (tx, ty)
        self._path.clear()
        self._steps_since_plan = 0
        self._reset_bug()

    def reset(self) -> None:
        """Clear the target and all navigation state."""
        self.target = None
        self._path.clear()
        self._steps_since_plan = 0
        self._reset_bug()

    def next_move(self, ct) -> Optional[Direction]:
        """
        Compute and return the next Direction to move toward the target.

        Returns None if already at the target, no target is set, or the
        bot is completely surrounded.  Does NOT move the bot or build roads.
        """
        if self.target is None:
            return None

        cur: Position = ct.get_position()
        tx, ty = self.target
        if cur.x == tx and cur.y == ty:
            return None

        # Grow the terrain cache from this round's visible tiles.
        self._update_terrain(ct)

        target_pos = Position(tx, ty)

        # ---- A* path following ----------------------------------------
        dir_from_astar = self._astar_step(ct, cur, target_pos)
        if dir_from_astar is not None:
            self._reset_bug()   # keep bug state clean for whenever we need it
            return dir_from_astar

        # ---- BugNav2 fallback -----------------------------------------
        return self._bug_next_move(ct, cur, target_pos)

    # ------------------------------------------------------------------
    # Terrain cache
    # ------------------------------------------------------------------

    def _update_terrain(self, ct) -> None:
        if not self._map_w:
            self._map_w = ct.get_map_width()
            self._map_h = ct.get_map_height()
        for t in ct.get_nearby_tiles():
            key = (t.x, t.y)
            if key not in self._terrain:
                self._terrain[key] = ct.get_tile_env(t)

    # ------------------------------------------------------------------
    # A* path management
    # ------------------------------------------------------------------

    def _astar_step(
        self, ct, cur: Position, target_pos: Position
    ) -> Optional[Direction]:
        """
        Follow or replan the A* path.  Returns the next Direction to take,
        or None if A* cannot find a path right now.
        """
        # Decide whether a replan is needed.
        needs_replan = (
            not self._path
            or self._steps_since_plan >= self._REPLAN_EVERY
        )
        if not needs_replan and self._path:
            # Invalidate if the next step became blocked (live vision check).
            nxt = self._path[0]
            if ct.is_in_vision(nxt) and not self._can_navigate(ct, nxt):
                needs_replan = True
                self._path.clear()

        if needs_replan:
            new_path = self._run_astar(cur, target_pos)
            if new_path:
                self._path = deque(new_path)
                self._steps_since_plan = 0
            else:
                self._path.clear()

        if not self._path:
            return None

        next_pos = self._path[0]

        # Re-validate for in-vision tiles (obstacles appear mid-path).
        if ct.is_in_vision(next_pos) and not self._can_navigate(ct, next_pos):
            self._path.clear()
            return None

        dx = next_pos.x - cur.x
        dy = next_pos.y - cur.y
        move_dir = _DELTA_TO_DIR.get((dx, dy))
        if move_dir is None:
            # Stale path — positions are no longer adjacent; replan next round.
            self._path.clear()
            return None

        self._path.popleft()
        self._steps_since_plan += 1
        return move_dir

    def _run_astar(self, start: Position, goal: Position) -> list:
        """
        A* from start to goal using the accumulated terrain cache.

        Known walls are hard blockers; unseen tiles are treated as passable
        (optimistic exploration).  Returns a list of Positions from
        start+1 step to goal (inclusive), or [] if unreachable / budget hit.
        """
        def h(p: Position) -> float:
            # Octile distance — admissible heuristic for 8-directional grids.
            dx = abs(p.x - goal.x)
            dy = abs(p.y - goal.y)
            mn, mx = (dx, dy) if dx < dy else (dy, dx)
            return mx + mn * (_SQRT2 - 1.0)

        open_heap: list = []
        self._uid += 1
        heappush(open_heap, (h(start), 0.0, self._uid, start))
        came_from: dict = {start: None}
        g: dict = {start: 0.0}

        nodes = 0
        while open_heap and nodes < self._MAX_ASTAR_NODES:
            _, g_cur, _, cur = heappop(open_heap)
            nodes += 1

            if cur == goal:
                # Reconstruct path excluding start, including goal.
                path: list = []
                p: Optional[Position] = goal
                while p is not None and p != start:
                    path.append(p)
                    p = came_from[p]
                path.reverse()
                return path

            # Lazy deletion: skip stale heap entries.
            if g_cur > g.get(cur, float("inf")) + 1e-9:
                continue

            for d in _ALL_DIRS:
                nxt = cur.add(d)
                if not self._astar_passable(nxt):
                    continue
                ddx, ddy = d.delta()
                step = _SQRT2 if ddx != 0 and ddy != 0 else 1.0
                ng = g_cur + step
                if ng < g.get(nxt, float("inf")) - 1e-9:
                    g[nxt] = ng
                    came_from[nxt] = cur
                    self._uid += 1
                    heappush(open_heap, (ng + h(nxt), ng, self._uid, nxt))

        return []   # goal unreachable or budget exhausted

    def _astar_passable(self, pos: Position) -> bool:
        """
        Passability for A* planning only (no controller access).
        Known walls → blocked.  Unknown tiles → optimistically open.
        """
        if self._map_w and not (0 <= pos.x < self._map_w and 0 <= pos.y < self._map_h):
            return False
        return self._terrain.get((pos.x, pos.y)) != Environment.WALL

    # ------------------------------------------------------------------
    # BugNav2 fallback
    # ------------------------------------------------------------------

    def _reset_bug(self) -> None:
        self._bug_mode = "direct"
        self._hit_dist_sq = 0
        self._last_dir = None
        self._boundary_steps = 0

    def _bug_next_move(
        self, ct, cur: Position, target_pos: Position
    ) -> Optional[Direction]:
        if self._bug_mode == "direct":
            return self._bug_direct(ct, cur, target_pos)
        return self._bug_boundary(ct, cur, target_pos)

    def _bug_direct(
        self, ct, cur: Position, target_pos: Position
    ) -> Optional[Direction]:
        best_dir = cur.direction_to(target_pos)
        for d in self._sorted_dirs(best_dir):
            nxt = cur.add(d)
            if self._can_navigate(ct, nxt):
                self._last_dir = d
                return d

        # All in-vision directions blocked — enter boundary following.
        self._bug_mode = "boundary"
        self._hit_dist_sq = cur.distance_squared(target_pos)
        self._boundary_steps = 0
        self._last_dir = cur.direction_to(target_pos)
        return self._bug_boundary(ct, cur, target_pos)

    def _bug_boundary(
        self, ct, cur: Position, target_pos: Position
    ) -> Optional[Direction]:
        self._boundary_steps += 1
        if self._boundary_steps > self._MAX_BOUNDARY_STEPS:
            self._reset_bug()
            return None

        # Escape: any direction that beats the entry-point distance.
        best_dir = cur.direction_to(target_pos)
        for d in self._sorted_dirs(best_dir):
            nxt = cur.add(d)
            if self._can_navigate(ct, nxt):
                if nxt.distance_squared(target_pos) < self._hit_dist_sq:
                    self._bug_mode = "direct"
                    self._last_dir = d
                    return d

        # Right-hand wall following: 90° clockwise from last travel dir.
        if self._last_dir is None:
            self._last_dir = best_dir
        probe = self._last_dir.rotate_right().rotate_right()
        for _ in range(8):
            nxt = cur.add(probe)
            if self._can_navigate(ct, nxt):
                self._last_dir = probe
                return probe
            probe = probe.rotate_left()

        return None     # Completely surrounded

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _sorted_dirs(self, best: Direction) -> list:
        """8 directions ordered by angular closeness to `best`."""
        dirs = [best]
        right = best
        left = best
        for _ in range(3):
            right = right.rotate_right()
            left = left.rotate_left()
            dirs.append(right)
            dirs.append(left)
        dirs.append(best.opposite())
        return dirs

    def _can_navigate(self, ct, to_pos: Position) -> bool:
        """
        Live passability check via the controller (requires tile in vision).
        EMPTY / ORE tiles are navigable — caller must build road first.
        Diagonal clipping is permitted: only the destination tile is checked.
        """
        if not ct.is_in_vision(to_pos):
            return False

        if ct.get_tile_env(to_pos) == Environment.WALL:
            return False

        building_id = ct.get_tile_building_id(to_pos)
        if building_id is not None:
            etype = ct.get_entity_type(building_id)
            if etype in (
                EntityType.ROAD,
                EntityType.CONVEYOR,
                EntityType.ARMOURED_CONVEYOR,
            ):
                pass    # passable infrastructure
            elif etype == EntityType.CORE:
                if ct.get_team(building_id) != ct.get_team():
                    return False    # enemy core blocks
            else:
                return False    # barrier, harvester, turret, etc.

        if ct.get_tile_builder_bot_id(to_pos) is not None:
            return False

        return True
