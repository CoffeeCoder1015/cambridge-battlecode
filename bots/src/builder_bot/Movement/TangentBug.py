from collections import deque
import sys
from cambc import Direction, Environment, EntityType, Position
from typing import Optional

_ALL_DIRS: tuple[Direction, ...] = tuple(d for d in Direction if d != Direction.CENTRE)

# Pre-compute sorted-by-angle order once for all 8 base directions.
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
    Fast BugNav2 navigator for builder bots. (Updated with deep passability logging)
    """

    _RECENT_WINDOW    = 8
    _MAX_BOUNDARY     = 200

    def __init__(
        self,
        debug_prints: bool = False,  
        debug_name: str = "main-nav",
    ) -> None:
        self.target: Optional[tuple[int, int]] = None
        self.debug_prints = debug_prints
        self.debug_name = debug_name

        self._mode: str = "direct"

        # Boundary state
        self._boundary_dir: Optional[Direction] = None
        self._follow_right: bool = True
        self._side_switched: bool = False
        self._boundary_steps: int = 0
        self._best_dist_sq: int = 0      
        self._boundary_seen: set[tuple[int, int, bool]] = set()
        self._last_pos_coords: Optional[tuple[int, int]] = None

        self._recent: deque[tuple[int, int]] = deque(maxlen=self._RECENT_WINDOW)
        self._pcache: dict[tuple[int, int], int] = {} 

        self._debug_round: int | None = None
        self._debug_logs_this_round = 0
        self._debug_max_logs_per_round = 50 # Increased log limit

    def _log(self, ct, message: str) -> None:
        if not self.debug_prints:
            return
        current_round = ct.get_current_round()
        if self._debug_round != current_round:
            self._debug_round = current_round
            self._debug_logs_this_round = 0
        if self._debug_logs_this_round >= self._debug_max_logs_per_round:
            return
        self._debug_logs_this_round += 1
        pos = ct.get_position()
        print(f"[TangentBug:{self.debug_name}][R{current_round}][{pos.x},{pos.y}] {message}", file=sys.stderr)

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
        self._last_pos_coords = None
        self._recent.clear()

    # ·· Direct mode ·····················································

    def _direct(self, ct, cur: Position, target_pos: Position) -> Optional[Direction]:
        best_dir = cur.direction_to(target_pos)
        dirs = _SORTED_DIRS[best_dir]
        recent = self._recent

        self._log(ct, f"Direct evaluation toward {target_pos.x},{target_pos.y}")

        # Pass 1: prefer moves not in recent history
        for d in dirs:
            nxt = cur.add(d)
            if self._tile_state(ct, nxt) == 0 and (nxt.x, nxt.y) not in recent:
                self._log(ct, f"Direct step selected: {d} to {nxt.x},{nxt.y} (fresh)")
                return d

        # Pass 2: allow recent tiles if no fresh option exists
        for d in dirs:
            nxt = cur.add(d)
            if self._tile_state(ct, nxt) == 0:
                self._log(ct, f"Direct step selected: {d} to {nxt.x},{nxt.y} (recent history)")
                return d

        # All options blocked.
        best_nxt = cur.add(best_dir)
        block_type = self._tile_state(ct, best_nxt)
        
        if block_type == 2:
            self._enter_boundary(cur, target_pos, best_dir)
            self._log(ct, f"Direct path hard-blocked at {best_nxt.x},{best_nxt.y}; entering boundary")
            return self._boundary(ct, cur, target_pos)
        else:
            self._log(ct, f"Direct path soft-blocked by bot at {best_nxt.x},{best_nxt.y}; yielding")
            return None

    # ·· Boundary mode ····················································

    def _enter_boundary(self, cur: Position, target_pos: Position, blocked_dir: Direction) -> None:
        self._mode = "boundary"
        self._boundary_dir = blocked_dir
        self._follow_right = True
        self._side_switched = False
        self._boundary_steps = 0
        self._boundary_seen.clear()
        self._last_pos_coords = None
        
        self._best_dist_sq = cur.distance_squared(target_pos)

    def _boundary(self, ct, cur: Position, target_pos: Position) -> Optional[Direction]:
        coords = (cur.x, cur.y)
        
        if coords != self._last_pos_coords:
            state = (cur.x, cur.y, self._follow_right)
            if state in self._boundary_seen:
                self._log(ct, "Boundary loop detected; attempting recovery")
                return self._stall_recovery(ct, cur, target_pos)
                
            self._boundary_seen.add(state)
            self._boundary_steps += 1
            self._last_pos_coords = coords

        if self._boundary_steps > self._MAX_BOUNDARY:
            self._log(ct, "Boundary step cap exceeded; attempting recovery")
            return self._stall_recovery(ct, cur, target_pos)

        # Escape check
        best_dir = cur.direction_to(target_pos)
        for d in _SORTED_DIRS[best_dir]:
            nxt = cur.add(d)
            if self._tile_state(ct, nxt) == 0 and nxt.distance_squared(target_pos) < self._best_dist_sq:
                self._mode = "direct"
                self._log(ct, f"Boundary exit to direct via {d}; dist_sq strictly closer.")
                return d

        # Wall-following step
        base = self._boundary_dir if self._boundary_dir is not None else best_dir
        for probe in _PROBE_DIRS[(base, self._follow_right)]:
            nxt = cur.add(probe)
            t_state = self._tile_state(ct, nxt)
            
            if t_state == 0:
                self._boundary_dir = probe
                self._log(ct, f"Boundary step selected: {probe} to {nxt.x},{nxt.y}")
                return probe
            elif t_state == 1:
                self._log(ct, f"Boundary path soft-blocked at {nxt.x},{nxt.y}; yielding to traffic")
                return None

        self._log(ct, "Boundary found no valid probe; attempting recovery")
        return self._stall_recovery(ct, cur, target_pos)

    def _stall_recovery(self, ct, cur: Position, target_pos: Position) -> Optional[Direction]:
        if not self._side_switched:
            self._follow_right = not self._follow_right
            self._side_switched = True
            self._boundary_steps = 0
            self._boundary_seen.clear()
            self._last_pos_coords = None
            self._log(ct, f"Stall recovery: switched follow side -> follow_right={self._follow_right}")
            
            base = self._boundary_dir if self._boundary_dir is not None else cur.direction_to(target_pos)
            for probe in _PROBE_DIRS[(base, self._follow_right)]:
                nxt = cur.add(probe)
                if self._tile_state(ct, nxt) == 0:
                    self._boundary_dir = probe
                    return probe

        self._reset()
        self._log(ct, "Stall recovery hard reset; fallback toward target")
        best_dir = cur.direction_to(target_pos)
        for d in _SORTED_DIRS[best_dir]:
            nxt = cur.add(d)
            if self._tile_state(ct, nxt) == 0:
                return d
        return None

    # ·· Passability ··················································

    def _tile_state(self, ct, pos: Position) -> int:
        key = (pos.x, pos.y)
        v = self._pcache.get(key)
        if v is not None:
            return v

        state: int = 0
        reason: str = "clear"
        w = ct.get_map_width()
        h = ct.get_map_height()
        
        if not (0 <= pos.x < w and 0 <= pos.y < h):
            state = 2
            reason = "OOB"
        elif not ct.is_in_vision(pos):
            state = 0  
            reason = "unseen (optimistic)"
        elif ct.get_tile_env(pos) == Environment.WALL:
            state = 2
            reason = "env_wall"
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
                    pass 
                elif et == EntityType.CORE and ct.get_team(bid) == ct.get_team():
                    pass
                else:
                    state = 2 
                    reason = f"blocking_bld_{et.name}"
                    
        if state == 0:
            bot_id = ct.get_tile_builder_bot_id(pos)
            if bot_id is not None:
                state = 1 
                reason = f"allied_bot_{bot_id}"

        self._pcache[key] = state
        # Deep logging for blocked states
        if state != 0 and self.debug_prints:
            self._log(ct, f"Eval {pos.x},{pos.y} -> Blocked: {reason}")
            
        return state