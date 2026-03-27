"""
Bug2-style navigator for builder bots with enhanced recovery and blacklisting.
"""

import sys
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
    _DEBUG_MAX_ROUND = 300
    _NEAR_TRAIL_REPULSE_COST = 70
    _DOUBLE_STEP_REPULSE_COST = 20_000
    _RECENT_TILE_PENALTY = 32
    # Reduced epsilon to prevent premature M-line exits in tight corridors
    _M_LINE_EPS = 2

    def __init__(self) -> None:
        self.target: tuple[int, int] | None = None
        self._start: tuple[int, int] | None = None
        self._terrain: dict[tuple[int, int], Environment] | None = None

        self._mode = "direct"
        self._wall_dir: Direction | None = None
        self._follow_right = True
        self._hit_pos: tuple[int, int] | None = None
        self._hit_dist_sq = 0
        self._side_switched = False
        self._boundary_steps = 0
        self._boundary_seen: set[tuple[int, int, bool]] = set()
        self._last_boundary_pos: tuple[int, int] | None = None

        self._recent: deque[tuple[int, int]] = deque(maxlen=self._RECENT_WINDOW)
        # Prevents re-entering the same trap immediately after a reset
        self._blacklist: dict[tuple[int, int], int] = {}
        self._visit_counts: dict[tuple[int, int], int] = {}
        self._trail_repulse: dict[tuple[int, int], int] = {}
        self._loop_repulse: dict[tuple[int, int], int] = {}
        self._pcache: dict[tuple[int, int], int] = {}

    def attach_terrain_memory(
        self, map_history: dict[tuple[int, int], Environment] | None
    ) -> None:
        self._terrain = map_history

    def set_target(self, tx: int, ty: int, cur_x: int, cur_y: int) -> None:
        if self.target == (tx, ty):
            return
        self.target = (tx, ty)
        self._start = (cur_x, cur_y)
        self._reset(clear_run_memory=True)

    def next_move(self, ct: Controller) -> Direction | None:
        if self.target is None:
            return None

        self._pcache.clear()
        cur = ct.get_position()
        tx, ty = self.target

        if cur.x == tx and cur.y == ty:
            # Target run is complete; clear per-run memory so the next path run starts fresh.
            self._reset(clear_run_memory=True)
            return None

        coords = (cur.x, cur.y)
        if not self._recent or self._recent[-1] != coords:
            self._recent.append(coords)
            self._record_step(coords)

        # Cleanup expired blacklist items
        curr_round = ct.get_current_round()
        self._blacklist = {k: v for k, v in self._blacklist.items() if v > curr_round}

        target_pos = Position(tx, ty)

        if self._mode == "direct":
            return self._direct_step(ct, cur, target_pos)
        return self._boundary_step(ct, cur, target_pos)

    def _reset(self, *, clear_run_memory: bool = False) -> None:
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
        if clear_run_memory:
            self._visit_counts.clear()
            self._trail_repulse.clear()
            self._loop_repulse.clear()

    def _record_step(self, coords: tuple[int, int]) -> None:
        cx, cy = coords
        # Minor repulsion on the walked path and its neighboring 3x3 region.
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                region = (cx + dx, cy + dy)
                weight = 2 if dx == 0 and dy == 0 else 1
                self._trail_repulse[region] = self._trail_repulse.get(region, 0) + weight

        count = self._visit_counts.get(coords, 0) + 1
        self._visit_counts[coords] = count
        if count == 2:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    region = (cx + dx, cy + dy)
                    self._loop_repulse[region] = self._loop_repulse.get(region, 0) + 1

    def _movement_score(self, nxt: Position, target: Position) -> int:
        coords = (nxt.x, nxt.y)
        score = nxt.distance_squared(target)
        score += self._trail_repulse.get(coords, 0) * self._NEAR_TRAIL_REPULSE_COST
        score += self._loop_repulse.get(coords, 0) * self._DOUBLE_STEP_REPULSE_COST
        if coords in self._recent:
            score += self._RECENT_TILE_PENALTY
        return score

    def _is_on_m_line(self, x: int, y: int) -> bool:
        if self._start is None or self.target is None:
            return True
        sx, sy = self._start
        tx, ty = self.target
        dx, dy = tx - sx, ty - sy
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return True
        cross_sq = (dy * x - dx * y + tx * sy - ty * sx) ** 2
        return cross_sq <= self._M_LINE_EPS * self._M_LINE_EPS * length_sq

    def _direct_step(
        self, ct: Controller, cur: Position, target: Position
    ) -> Direction | None:
        best_dir = cur.direction_to(target)
        dirs = _SORTED_DIRS[best_dir]
        cur_dist_sq = cur.distance_squared(target)
        best_fresh: Direction | None = None
        best_fresh_score = 10**12
        best_progress: Direction | None = None
        best_progress_score = 10**12

        for i, d in enumerate(dirs):
            nxt = cur.add(d)
            nxt_coords = (nxt.x, nxt.y)
            if self._tile_state(ct, nxt) != 0 or nxt_coords in self._blacklist:
                continue
            if nxt.distance_squared(target) >= cur_dist_sq:
                continue
            score = self._movement_score(nxt, target) + i
            if nxt_coords not in self._recent and score < best_fresh_score:
                best_fresh = d
                best_fresh_score = score
            if score < best_progress_score:
                best_progress = d
                best_progress_score = score

        if best_fresh is not None:
            return best_fresh
        if best_progress is not None:
            return best_progress

        ideal_state = self._tile_state(ct, cur.add(best_dir))
        if ideal_state == 1:
            return None

        self._enter_boundary(ct, cur, target, best_dir)
        return self._boundary_step(ct, cur, target)

    def _enter_boundary(
        self,
        ct: Controller,
        cur: Position,
        target: Position,
        blocked_dir: Direction,
    ) -> None:
        self._mode = "boundary"
        self._wall_dir = blocked_dir
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
        right_d = next(
            (d for d in _PROBE_DIRS[(blocked, True)] if self._tile_state(ct, cur.add(d)) == 0),
            None,
        )
        left_d = next(
            (d for d in _PROBE_DIRS[(blocked, False)] if self._tile_state(ct, cur.add(d)) == 0),
            None,
        )
        if right_d is None: return False
        if left_d is None: return True
        right_score = self._movement_score(cur.add(right_d), target)
        left_score = self._movement_score(cur.add(left_d), target)
        return right_score <= left_score

    def _boundary_step(
        self, ct: Controller, cur: Position, target: Position
    ) -> Direction | None:
        coords = (cur.x, cur.y)

        if coords != self._last_boundary_pos:
            key = (cur.x, cur.y, self._follow_right)
            if key in self._boundary_seen:
                return self._recover(ct, cur, target)
            self._boundary_seen.add(key)
            self._boundary_steps += 1
            self._last_boundary_pos = coords

        if self._boundary_steps > self._MAX_BOUNDARY_STEPS:
            return self._recover(ct, cur, target)

        curr_dist_sq = cur.distance_squared(target)
        if (
            coords != self._hit_pos
            and curr_dist_sq < self._hit_dist_sq
            and self._is_on_m_line(cur.x, cur.y)
        ):
            self._mode = "direct"
            return self._direct_step(ct, cur, target)

        base = self._wall_dir if self._wall_dir is not None else cur.direction_to(target)
        saw_soft = False
        best_dir: Direction | None = None
        best_score = 10**12
        for i, d in enumerate(_PROBE_DIRS[(base, self._follow_right)]):
            nxt = cur.add(d)
            state = self._tile_state(ct, nxt)
            if state == 0:
                score = self._movement_score(nxt, target) + i
                if score < best_score:
                    best_score = score
                    best_dir = d
            if state == 1:
                saw_soft = True

        if best_dir is not None:
            self._wall_dir = best_dir
            return best_dir
        if saw_soft: return None
        return self._recover(ct, cur, target)

    def _recover(
        self, ct: Controller, cur: Position, target: Position
    ) -> Direction | None:
        if not self._side_switched:
            self._follow_right = not self._follow_right
            self._side_switched = True
            self._boundary_steps = 0
            self._boundary_seen.clear()
            # TWEAK: Update hit point so the new side can escape based on local progress
            self._hit_pos = (cur.x, cur.y)
            self._hit_dist_sq = cur.distance_squared(target)
            
            base = self._wall_dir if self._wall_dir is not None else cur.direction_to(target)
            for d in _PROBE_DIRS[(base, self._follow_right)]:
                if self._tile_state(ct, cur.add(d)) == 0:
                    self._wall_dir = d
                    return d

        # TWEAK: Blacklist this coordinate for a few rounds to force a different path
        self._blacklist[(cur.x, cur.y)] = ct.get_current_round() + 10
        self._reset()
        best = cur.direction_to(target)
        for d in _SORTED_DIRS[best]:
            if self._tile_state(ct, cur.add(d)) == 0:
                return d
        return None

    def _tile_state(self, ct: Controller, pos: Position) -> int:
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
        if self._terrain is not None and self._terrain.get(key) == Environment.WALL:
            return 2
        if not ct.is_in_vision(pos):
            return 0

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

    def _dbg(self, ct: Controller, msg: str) -> None:
        if ct.get_current_round() < self._DEBUG_MAX_ROUND:
            pos = ct.get_position()
            print(f"[R{ct.get_current_round()}][TN][{pos.x},{pos.y}] {msg}", file=sys.stderr)