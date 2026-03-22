from cambc import Direction, Environment, EntityType, Position
from typing import Optional


class TangentBug:
    """
    BugNav2-style grid navigator for builder bots.

    The algorithm moves directly toward the target and, when blocked,
    follows the obstacle boundary with a right-hand rule until it can
    escape to a tile strictly closer to the target than the entry point.

    Passability rules used for planning:
    - WALL tiles are never navigable.
    - EMPTY / ORE tiles are treated as navigable (caller must build road).
    - ROAD, CONVEYOR, ARMOURED_CONVEYOR tiles are passable.
    - The friendly CORE tile is passable.
    - Tiles occupied by another builder bot are not navigable.
    - Diagonal moves clip freely through wall corners (only target tile checked).

    Road placement and actual movement are the caller's responsibility.

    Usage:
        nav = TangentBug()
        nav.set_target(tx, ty)        # set destination once
        direction = nav.next_move(ct)  # call every turn; returns Direction or None
        nav.reset()                    # clear target and all state
    """

    _MAX_BOUNDARY_STEPS = 256

    def __init__(self) -> None:
        self.target: Optional[tuple[int, int]] = None
        self._mode: str = "direct"       # "direct" | "boundary"
        self._hit_dist_sq: int = 0       # dist² at the moment boundary mode was entered
        self._last_dir: Optional[Direction] = None
        self._boundary_steps: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_target(self, tx: int, ty: int) -> None:
        """Set a new navigation target and reset internal state."""
        self.target = (tx, ty)
        self._reset_nav()

    def reset(self) -> None:
        """Clear the target and all navigation state."""
        self.target = None
        self._reset_nav()

    def next_move(self, ct) -> Optional[Direction]:
        """
        Compute and return the next direction to move toward the target.

        Returns None when:
        - No target has been set.
        - The bot is already at the target.
        - The bot is completely surrounded and cannot move.

        This method does NOT move the bot or build roads.
        """
        if self.target is None:
            return None

        cur: Position = ct.get_position()
        tx, ty = self.target
        if cur.x == tx and cur.y == ty:
            return None

        target_pos = Position(tx, ty)
        if self._mode == "direct":
            return self._step_direct(ct, cur, target_pos)
        return self._step_boundary(ct, cur, target_pos)

    # ------------------------------------------------------------------
    # Navigation internals
    # ------------------------------------------------------------------

    def _reset_nav(self) -> None:
        self._mode = "direct"
        self._hit_dist_sq = 0
        self._last_dir = None
        self._boundary_steps = 0

    def _step_direct(
        self, ct, cur: Position, target_pos: Position
    ) -> Optional[Direction]:
        best_dir = cur.direction_to(target_pos)
        for d in self._sorted_dirs(best_dir):
            nxt = cur.add(d)
            if self._can_navigate(ct, nxt):
                self._last_dir = d
                return d

        # All directions blocked — enter boundary following
        self._mode = "boundary"
        self._hit_dist_sq = cur.distance_squared(target_pos)
        self._boundary_steps = 0
        self._last_dir = cur.direction_to(target_pos)
        return self._step_boundary(ct, cur, target_pos)

    def _step_boundary(
        self, ct, cur: Position, target_pos: Position
    ) -> Optional[Direction]:
        self._boundary_steps += 1
        if self._boundary_steps > self._MAX_BOUNDARY_STEPS:
            # Obstacle likely encloses the bot; reset and let direct mode retry.
            self._reset_nav()
            return None

        # Escape check: any navigable direction that beats the entry distance?
        best_dir = cur.direction_to(target_pos)
        for d in self._sorted_dirs(best_dir):
            nxt = cur.add(d)
            if self._can_navigate(ct, nxt):
                if nxt.distance_squared(target_pos) < self._hit_dist_sq:
                    self._mode = "direct"
                    self._last_dir = d
                    return d

        # Right-hand rule boundary following.
        # Start probing 90° clockwise from the last travel direction, then
        # sweep counter-clockwise until a free direction is found.
        if self._last_dir is None:
            self._last_dir = best_dir

        probe = self._last_dir.rotate_right().rotate_right()  # 90° clockwise
        for _ in range(8):
            nxt = cur.add(probe)
            if self._can_navigate(ct, nxt):
                self._last_dir = probe
                return probe
            probe = probe.rotate_left()

        return None  # Completely surrounded

    def _sorted_dirs(self, best: Direction) -> list:
        """
        Return all 8 movement directions ordered by angular closeness to `best`.
        Order: best, ±45°, ±90°, ±135°, 180°.
        """
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
        Return True if `to_pos` is a valid target for pathfinding.

        EMPTY and ORE tiles are considered navigable here — the caller is
        responsible for building a road before the bot actually steps there.
        Diagonal clipping through wall corners is permitted: only the target
        tile itself is checked, not the orthogonal neighbours.
        """
        if not self._is_in_map_bounds(ct, to_pos):
            return False

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
                pass  # passable infrastructure
            elif etype == EntityType.CORE:
                if ct.get_team(building_id) != ct.get_team():
                    return False  # enemy core blocks movement
            else:
                # Barriers, harvesters, turrets, splitters, etc. all block.
                return False

        if ct.get_tile_builder_bot_id(to_pos) is not None:
            return False

        return True

    @staticmethod
    def _is_in_map_bounds(ct, pos: Position) -> bool:
        return 0 <= pos.x < ct.get_map_width() and 0 <= pos.y < ct.get_map_height()
