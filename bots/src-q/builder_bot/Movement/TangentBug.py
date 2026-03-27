from collections import deque
from cambc import Direction, Environment, EntityType, Position
from typing import Optional

_ALL_DIRS: tuple[Direction, ...] = tuple(d for d in Direction if d != Direction.CENTRE)

# Pre-compute sorted-by-angle order once for all 8 base directions.
# Maps Direction -> tuple of all 8 dirs ordered closest to farthest angle.
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

_SORTED_DIRS: dict[Direction, tuple[Direction, ...]] = _build_sorted_cache()

# Pre-compute boundary probe order (right-hand and left-hand) for all base dirs.
def _build_probe_cache() -> dict[tuple[Direction, bool], tuple[Direction, ...]]:
    cache: dict[tuple[Direction, bool], tuple[Direction, ...]] = {}
    for base in _ALL_DIRS:
        for right_hand in (True, False):
            seq: list[Direction] = []
            if right_hand:
                p = base.rotate_right().rotate_right()
                for _ in range(8):
                    seq.append(p)
                    p = p.rotate_left()
            else:
                p = base.rotate_left().rotate_left()
                for _ in range(8):
                    seq.append(p)
                    p = p.rotate_right()
            cache[(base, right_hand)] = tuple(seq)
    return cache

_PROBE_DIRS: dict[tuple[Direction, bool], tuple[Direction, ...]] = _build_probe_cache()


class TangentBug:
    """
    Fast BugNav2 navigator for builder bots.

    Strategy:
      DIRECT  — pick the navigable direction closest in angle to the target,
                deprioritising tiles visited in the last few turns so the bot
                naturally avoids ping-pong loops without any detection overhead.
      BOUNDARY — right-hand (or left-hand) wall following.  Exits as soon as
                 any direction leads to a tile strictly closer to the target
                 than the best distance seen so far during this episode.
                 Loop detection: if the bot revisits a (tile, side) state it
                 already traced this episode, flip to the other side once; if
                 that also loops, hard-reset.

    Passability:
      - WALL tiles block.
      - EMPTY / ORE are navigable (caller builds road).
      - ROAD, CONVEYOR, ARMOURED_CONVEYOR pass (any team).
      - Friendly CORE passes; enemy CORE blocks.
      - Tiles occupied by another builder bot block.
      - Diagonal corner-clipping is allowed (only target tile checked).

    Public API:
        nav = TangentBug()
        nav.set_target(tx, ty)
        direction = nav.next_move(ct)   # call every turn; returns Direction|None
        nav.reset()
    """

    _RECENT_WINDOW    = 8    # how many past positions to remember for oscillation avoidance
    _MAX_BOUNDARY     = 200  # hard step cap before boundary gives up
    _DIRECT_PENALTY   = 4    # how many extra positions in recent-history penalty

    def __init__(self) -> None:
        self.target: Optional[tuple[int, int]] = None

        # Mode: "direct" or "boundary"
        self._mode: str = "direct"

        # Boundary state
        self._boundary_dir: Optional[Direction] = None  # last travel direction on boundary
        self._follow_right: bool = True
        self._side_switched: bool = False
        self._boundary_steps: int = 0
        self._best_dist_sq: int = 0      # best dist² seen since entering boundary
        self._boundary_seen: set[tuple[int, int, bool]] = set()

        # Recent position history — used in direct mode to deprioritise backtracking
        self._recent: deque[tuple[int, int]] = deque(maxlen=self._RECENT_WINDOW)

        # Per-turn tile passability cache (cleared each call)
        self._pcache: dict[tuple[int, int], bool] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_target(self, tx: int, ty: int) -> None:
        self.target = (tx, ty)
        self._reset()

    def reset(self) -> None:
        self.target = None
        self._reset()

    def next_move(self, ct) -> Optional[Direction]:
        """Return the next Direction to move, or None if at target / unreachable."""
        if self.target is None:
            return None

        self._pcache.clear()
        cur: Position = ct.get_position()
        tx, ty = self.target
        if cur.x == tx and cur.y == ty:
            return None

        self._recent.append((cur.x, cur.y))
        target_pos = Position(tx, ty)

        if self._mode == "direct":
            return self._direct(ct, cur, target_pos)
        return self._boundary(ct, cur, target_pos)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _reset(self) -> None:
        self._mode = "direct"
        self._boundary_dir = None
        self._follow_right = True
        self._side_switched = False
        self._boundary_steps = 0
        self._best_dist_sq = 0
        self._boundary_seen.clear()
        self._recent.clear()

    # ·· Direct mode ·····················································

    def _direct(self, ct, cur: Position, target_pos: Position) -> Optional[Direction]:
        best_dir = cur.direction_to(target_pos)
        dirs = _SORTED_DIRS[best_dir]
        recent = self._recent

        # Pass 1: prefer moves not in recent history
        for d in dirs:
            nxt = cur.add(d)
            if self._ok(ct, nxt) and (nxt.x, nxt.y) not in recent:
                return d

        # Pass 2: allow recent tiles if no fresh option exists
        for d in dirs:
            nxt = cur.add(d)
            if self._ok(ct, nxt):
                return d

        # All directions blocked — start boundary following
        self._enter_boundary(cur, target_pos, cur.direction_to(target_pos))
        return self._boundary(ct, cur, target_pos)

    # ·· Boundary mode ····················································

    def _enter_boundary(
        self, cur: Position, target_pos: Position, blocked_dir: Direction
    ) -> None:
        self._mode = "boundary"
        self._boundary_dir = blocked_dir
        self._follow_right = True
        self._side_switched = False
        self._boundary_steps = 0
        self._best_dist_sq = cur.distance_squared(target_pos)
        self._boundary_seen.clear()

    def _boundary(self, ct, cur: Position, target_pos: Position) -> Optional[Direction]:
        # Loop detection
        state = (cur.x, cur.y, self._follow_right)
        if state in self._boundary_seen:
            return self._stall_recovery(ct, cur, target_pos)
        self._boundary_seen.add(state)

        self._boundary_steps += 1
        if self._boundary_steps > self._MAX_BOUNDARY:
            return self._stall_recovery(ct, cur, target_pos)

        # Update best distance seen during this episode
        cur_d = cur.distance_squared(target_pos)
        if cur_d < self._best_dist_sq:
            self._best_dist_sq = cur_d

        # Escape check: can we step somewhere strictly closer than best so far?
        best_dir = cur.direction_to(target_pos)
        for d in _SORTED_DIRS[best_dir]:
            nxt = cur.add(d)
            if self._ok(ct, nxt) and nxt.distance_squared(target_pos) < self._best_dist_sq:
                self._mode = "direct"
                return d

        # Wall-following step
        base = self._boundary_dir if self._boundary_dir is not None else best_dir
        for probe in _PROBE_DIRS[(base, self._follow_right)]:
            nxt = cur.add(probe)
            if self._ok(ct, nxt):
                self._boundary_dir = probe
                return probe

        return self._stall_recovery(ct, cur, target_pos)

    def _stall_recovery(self, ct, cur: Position, target_pos: Position) -> Optional[Direction]:
        # Try flipping the follow side once
        if not self._side_switched:
            self._follow_right = not self._follow_right
            self._side_switched = True
            self._boundary_steps = 0
            self._boundary_seen.clear()
            # Attempt one boundary step with the new side immediately
            base = self._boundary_dir if self._boundary_dir is not None else cur.direction_to(target_pos)
            for probe in _PROBE_DIRS[(base, self._follow_right)]:
                nxt = cur.add(probe)
                if self._ok(ct, nxt):
                    self._boundary_dir = probe
                    return probe

        # Hard reset — obstacle may fully enclose the bot or the path is dynamic.
        # Fall back to any navigable move toward target (ignoring recent history).
        self._reset()
        best_dir = cur.direction_to(target_pos)
        for d in _SORTED_DIRS[best_dir]:
            nxt = cur.add(d)
            if self._ok(ct, nxt):
                return d
        return None

    # ·· Passability ··················································

    def _ok(self, ct, pos: Position) -> bool:
        key = (pos.x, pos.y)
        v = self._pcache.get(key)
        if v is not None:
            return v

        ok: bool
        w = ct.get_map_width()
        h = ct.get_map_height()
        if not (0 <= pos.x < w and 0 <= pos.y < h):
            ok = False
        elif not ct.is_in_vision(pos):
            ok = False
        elif ct.get_tile_env(pos) == Environment.WALL:
            ok = False
        else:
            bid = ct.get_tile_building_id(pos)
            if bid is not None:
                et = ct.get_entity_type(bid)
                if et in (
                    EntityType.ROAD,
                    EntityType.BRIDGE,
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                ):
                    ok = True
                elif et == EntityType.CORE:
                    ok = ct.get_team(bid) == ct.get_team()
                else:
                    ok = False
            else:
                ok = ct.get_tile_builder_bot_id(pos) is None

        self._pcache[key] = ok
        return ok
