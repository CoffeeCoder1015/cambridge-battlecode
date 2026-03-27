"""
Bug2-style navigator for builder bots.

States
------
direct   : Greedily move toward target, preferring tiles not recently visited.
boundary : Wall-follow (right- or left-hand rule) until the M-line is crossed
           at a point strictly closer to the target than where the obstacle
           was first hit.  The M-line and the hit-distance are locked when
           boundary mode is entered and never change during the traversal,
           avoiding the drift bug present when an "effective target" shifts
           mid-wall-follow.
"""

import math
from collections import deque

from cambc import Controller, Direction, Environment, EntityType, Position

_ALL_DIRS: tuple[Direction, ...] = tuple(d for d in Direction if d != Direction.CENTRE)
_PASSABLE_BUILDINGS: tuple[EntityType, ...] = (
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
)


def _build_sorted_cache() -> dict[Direction, tuple[Direction, ...]]:
    """Directions sorted by angular proximity to each base direction."""
    cache: dict[Direction, tuple[Direction, ...]] = {}
    for base in _ALL_DIRS:
        dirs = [base]
        r, l = base, base
        for _ in range(3):
            r = r.rotate_right()
            l = l.rotate_left()
            dirs.append(r)
            dirs.append(l)
        dirs.append(base.opposite())
        cache[base] = tuple(dirs)
    return cache


def _build_probe_cache() -> dict[tuple[Direction, bool], tuple[Direction, ...]]:
    """Wall-follow probe sequences for right-hand and left-hand traversal."""
    cache: dict[tuple[Direction, bool], tuple[Direction, ...]] = {}
    for base in _ALL_DIRS:
        for follow_right in (True, False):
            seq: list[Direction] = []
            if follow_right:
                p = base.rotate_right().rotate_right()
                for _ in range(8):
                    seq.append(p)
                    p = p.rotate_left()
            else:
                p = base.rotate_left().rotate_left()
                for _ in range(8):
                    seq.append(p)
                    p = p.rotate_right()
            cache[(base, follow_right)] = tuple(seq)
    return cache


_SORTED_DIRS: dict[Direction, tuple[Direction, ...]] = _build_sorted_cache()
_PROBE_DIRS: dict[tuple[Direction, bool], tuple[Direction, ...]] = _build_probe_cache()


class TangentNav:
    _RECENT_WINDOW = 8
    _MAX_BOUNDARY_STEPS = 300
    # Maximum perpendicular distance from the M-line that counts as "on" it.
    # 1.0 tile ensures we catch crossings even for diagonal M-lines where the
    # closest reachable grid cell sits ~0.7 units from the ideal line.
    _M_LINE_EPS = 1.0

    def __init__(self) -> None:
        self.target: tuple[int, int] | None = None
        self._start: tuple[int, int] | None = None
        self._terrain: dict[tuple[int, int], Environment] | None = None

        # --- mode state ---
        self._mode = "direct"
        self._wall_dir: Direction | None = None
        self._follow_right = True
        # Locked when entering boundary mode; never mutated during traversal.
        self._hit_pos: tuple[int, int] | None = None
        self._hit_dist_sq = 0
        self._side_switched = False
        self._boundary_steps = 0
        self._boundary_seen: set[tuple[int, int, bool]] = set()
        self._last_boundary_pos: tuple[int, int] | None = None

        self._recent: deque[tuple[int, int]] = deque(maxlen=self._RECENT_WINDOW)
        self._pcache: dict[tuple[int, int], int] = {}

    # ------------------------------------------------------------------
    # Public API (matches the interface expected by builder_bot/main.py)
    # ------------------------------------------------------------------

    def attach_terrain_memory(
        self, map_history: dict[tuple[int, int], Environment] | None
    ) -> None:
        self._terrain = map_history

    def set_target(self, tx: int, ty: int, cur_x: int, cur_y: int) -> None:
        if self.target == (tx, ty):
            return
        self.target = (tx, ty)
        self._start = (cur_x, cur_y)
        self._reset()

    def next_move(self, ct: Controller) -> Direction | None:
        if self.target is None:
            return None

        self._pcache.clear()
        cur = ct.get_position()
        tx, ty = self.target

        if cur.x == tx and cur.y == ty:
            return None

        coords = (cur.x, cur.y)
        if not self._recent or self._recent[-1] != coords:
            self._recent.append(coords)

        target_pos = Position(tx, ty)

        if self._mode == "direct":
            return self._direct_step(ct, cur, target_pos)
        return self._boundary_step(ct, cur, target_pos)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _reset(self) -> None:
        self._mode = "direct"
        self._wall_dir = None
        self._follow_right = True
        self._hit_pos = None
        self._hit_dist_sq = 0
        self._side_switched = False
        self._boundary_steps = 0
        self._boundary_seen.clear()
        self._last_boundary_pos = None
        self._recent.clear()

    # ------------------------------------------------------------------
    # M-line geometry
    # ------------------------------------------------------------------

    def _is_on_m_line(self, x: int, y: int) -> bool:
        """True if (x, y) is within _M_LINE_EPS tiles of the start→target line."""
        if self._start is None or self.target is None:
            return True
        sx, sy = self._start
        tx, ty = self.target
        dx, dy = tx - sx, ty - sy
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return True
        # Squared perpendicular distance = (cross product)^2 / length^2
        cross_sq = (dy * x - dx * y + tx * sy - ty * sx) ** 2
        return cross_sq <= self._M_LINE_EPS * self._M_LINE_EPS * length_sq

    # ------------------------------------------------------------------
    # Direct mode
    # ------------------------------------------------------------------

    def _direct_step(
        self, ct: Controller, cur: Position, target: Position
    ) -> Direction | None:
        best_dir = cur.direction_to(target)
        dirs = _SORTED_DIRS[best_dir]
        cur_dist_sq = cur.distance_squared(target)

        # Pass 1: strictly closer AND not recently visited
        for d in dirs:
            nxt = cur.add(d)
            if self._tile_state(ct, nxt) != 0:
                continue
            if (
                nxt.distance_squared(target) < cur_dist_sq
                and (nxt.x, nxt.y) not in self._recent
            ):
                return d

        # Pass 2: strictly closer (allow recently visited as fallback)
        for d in dirs:
            nxt = cur.add(d)
            if self._tile_state(ct, nxt) != 0:
                continue
            if nxt.distance_squared(target) < cur_dist_sq:
                return d

        # No progress move found — check why the ideal tile is blocked.
        ideal_state = self._tile_state(ct, cur.add(best_dir))
        if ideal_state == 1:
            # Another bot is in the way — yield and wait.
            return None

        # Hard wall or fully enclosed — enter boundary mode.
        self._enter_boundary(ct, cur, target, best_dir)
        return self._boundary_step(ct, cur, target)

    # ------------------------------------------------------------------
    # Boundary mode
    # ------------------------------------------------------------------

    def _enter_boundary(
        self,
        ct: Controller,
        cur: Position,
        target: Position,
        blocked_dir: Direction,
    ) -> None:
        self._mode = "boundary"
        self._wall_dir = blocked_dir
        # Lock these values; they must not change during the traversal.
        self._hit_pos = (cur.x, cur.y)
        self._hit_dist_sq = cur.distance_squared(target)
        self._side_switched = False
        self._boundary_steps = 0
        self._boundary_seen.clear()
        self._last_boundary_pos = None
        self._follow_right = self._pick_side(ct, cur, target, blocked_dir)

    def _pick_side(
        self,
        ct: Controller,
        cur: Position,
        target: Position,
        blocked: Direction,
    ) -> bool:
        """Choose whichever side's first reachable step is closer to target."""
        right_d = next(
            (d for d in _PROBE_DIRS[(blocked, True)] if self._tile_state(ct, cur.add(d)) == 0),
            None,
        )
        left_d = next(
            (d for d in _PROBE_DIRS[(blocked, False)] if self._tile_state(ct, cur.add(d)) == 0),
            None,
        )
        if right_d is None:
            return False
        if left_d is None:
            return True
        return (
            cur.add(right_d).distance_squared(target)
            <= cur.add(left_d).distance_squared(target)
        )

    def _boundary_step(
        self, ct: Controller, cur: Position, target: Position
    ) -> Direction | None:
        coords = (cur.x, cur.y)

        # Track distinct positions to detect full loops.
        if coords != self._last_boundary_pos:
            key = (cur.x, cur.y, self._follow_right)
            if key in self._boundary_seen:
                return self._recover(ct, cur, target)
            self._boundary_seen.add(key)
            self._boundary_steps += 1
            self._last_boundary_pos = coords

        if self._boundary_steps > self._MAX_BOUNDARY_STEPS:
            return self._recover(ct, cur, target)

        # M-line escape: on the M-line AND strictly closer than the hit point.
        curr_dist_sq = cur.distance_squared(target)
        if (
            coords != self._hit_pos
            and curr_dist_sq < self._hit_dist_sq
            and self._is_on_m_line(cur.x, cur.y)
        ):
            self._mode = "direct"
            return self._direct_step(ct, cur, target)

        # Wall-follow: probe in the pre-computed order for the current side.
        base = self._wall_dir if self._wall_dir is not None else cur.direction_to(target)
        saw_soft = False
        for d in _PROBE_DIRS[(base, self._follow_right)]:
            nxt = cur.add(d)
            state = self._tile_state(ct, nxt)
            if state == 0:
                self._wall_dir = d
                return d
            if state == 1:
                saw_soft = True

        if saw_soft:
            return None  # Blocked by bots; wait for them to move.
        return self._recover(ct, cur, target)

    def _recover(
        self, ct: Controller, cur: Position, target: Position
    ) -> Direction | None:
        """Try flipping the follow side; full reset as last resort."""
        if not self._side_switched:
            self._follow_right = not self._follow_right
            self._side_switched = True
            self._boundary_steps = 0
            self._boundary_seen.clear()
            self._last_boundary_pos = None
            base = self._wall_dir if self._wall_dir is not None else cur.direction_to(target)
            for d in _PROBE_DIRS[(base, self._follow_right)]:
                nxt = cur.add(d)
                if self._tile_state(ct, nxt) == 0:
                    self._wall_dir = d
                    return d

        # Full reset and greedy fallback.
        self._reset()
        best = cur.direction_to(target)
        for d in _SORTED_DIRS[best]:
            if self._tile_state(ct, cur.add(d)) == 0:
                return d
        return None

    # ------------------------------------------------------------------
    # Tile passability
    # ------------------------------------------------------------------

    def _tile_state(self, ct: Controller, pos: Position) -> int:
        """
        0 = passable
        1 = soft block (another builder bot — yield, don't wall-follow)
        2 = hard block (wall, impassable building, out of bounds)
        """
        key = (pos.x, pos.y)
        cached = self._pcache.get(key)
        if cached is not None:
            return cached
        result = self._compute_state(ct, pos, key)
        self._pcache[key] = result
        return result

    def _compute_state(
        self, ct: Controller, pos: Position, key: tuple[int, int]
    ) -> int:
        w, h = ct.get_map_width(), ct.get_map_height()
        if not (0 <= pos.x < w and 0 <= pos.y < h):
            return 2

        # Terrain memory can short-circuit vision checks.
        if self._terrain is not None and self._terrain.get(key) == Environment.WALL:
            return 2

        if not ct.is_in_vision(pos):
            return 0  # Optimistic: treat unseen tiles as passable.

        env = ct.get_tile_env(pos)
        if self._terrain is not None:
            self._terrain[key] = env

        if env == Environment.WALL:
            return 2

        bid = ct.get_tile_building_id(pos)
        if bid is not None:
            etype = ct.get_entity_type(bid)
            own_core = etype == EntityType.CORE and ct.get_team(bid) == ct.get_team()
            if not own_core and etype not in _PASSABLE_BUILDINGS:
                return 2

        if ct.get_tile_builder_bot_id(pos) is not None:
            return 1

        return 0
