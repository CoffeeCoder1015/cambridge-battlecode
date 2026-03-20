"""
BugNav2 — navigate away from the core toward the opposite side of the map.

Algorithm:
  DIRECT mode : move straight toward the target.
  HUGGING mode: follow the wall (right-hand rule) until we reach a point
                strictly closer to the target than where we started hugging,
                then switch back to DIRECT.

The target is chosen as roughly the opposite corner of the map from the core,
with random jitter so multiple bots fan out across the board.

Usage (from main.py):
    pathing = BugNav2(core_pos=(cx, cy), map_w=w, map_h=h)
    direction = pathing.get_direction(ct)   # call each turn
"""

import random
import sys

from cambc import Controller, Direction, Environment, Position


# Directions ordered N → NE → E → ... (no CENTRE)
_ALL_DIRS = [d for d in Direction if d != Direction.CENTRE]


class BugNav2:
    def __init__(self, core_pos: tuple[int, int], map_w: int, map_h: int):
        self.core_pos = core_pos
        self.map_w = map_w
        self.map_h = map_h

        self.target: tuple[int, int] = self._pick_target()

        # BugNav2 internal state
        self._hugging = False
        self._hug_dir: Direction | None = None
        self._hug_start_dist: int | None = None
        self._hug_steps: int = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_direction(self, ct: Controller) -> Direction | None:
        """
        Return the Direction the bot should move this turn, or None if
        no move is appropriate (arrived at target, or completely stuck).

        Does NOT call ct.move() — the caller is responsible for actually
        moving (and optionally building a road first).
        """
        pos = ct.get_position()
        dist = self._dist_sq(pos.x, pos.y, *self.target)

        # Arrived — pick a fresh target
        if dist <= 2:
            self.target = self._pick_target()
            self._reset_hug()
            dist = self._dist_sq(pos.x, pos.y, *self.target)

        if not self._hugging:
            return self._direct(ct, pos, dist)
        return self._hug(ct, pos, dist)

    # ------------------------------------------------------------------
    # Target selection
    # ------------------------------------------------------------------

    def _pick_target(self) -> tuple[int, int]:
        """
        Pick a target roughly opposite the core on the map, with jitter
        so different bots explore different areas.
        """
        cx, cy = self.core_pos
        opp_x = self.map_w - 1 - cx
        opp_y = self.map_h - 1 - cy

        jitter = max(self.map_w, self.map_h) // 4
        tx = max(0, min(self.map_w - 1, opp_x + random.randint(-jitter, jitter)))
        ty = max(0, min(self.map_h - 1, opp_y + random.randint(-jitter, jitter)))

        print(
            f"[BugNav2 core={self.core_pos}] New target: ({tx}, {ty})",
            file=sys.stderr,
        )
        return (tx, ty)

    # ------------------------------------------------------------------
    # DIRECT mode
    # ------------------------------------------------------------------

    def _direct(self, ct: Controller, pos: Position, dist: int) -> Direction | None:
        target_pos = Position(self.target[0], self.target[1])
        ideal_dir = pos.direction_to(target_pos)

        # Try ideal direction, then ±45° neighbours
        for candidate in self._dir_preference(ideal_dir):
            if self._can_traverse(ct, pos, candidate):
                return candidate

        # All neighbours blocked — enter hugging mode
        self._hugging = True
        self._hug_dir = ideal_dir.rotate_left()
        self._hug_start_dist = dist
        self._hug_steps = 0
        return self._hug(ct, pos, dist)

    # ------------------------------------------------------------------
    # HUGGING mode
    # ------------------------------------------------------------------

    def _hug(self, ct: Controller, pos: Position, dist: int) -> Direction | None:
        # If we have reached a point strictly closer than where we started
        # hugging, drop back to DIRECT
        if self._hug_steps > 0 and dist < self._hug_start_dist:
            self._reset_hug()
            return self._direct(ct, pos, dist)

        # Safety valve — pick a new target if stuck for too long
        if self._hug_steps > (self.map_w + self.map_h) * 2:
            self.target = self._pick_target()
            self._reset_hug()
            return None

        # Right-hand wall rule: try to rotate right until we find a free dir
        for _ in range(8):
            if self._can_traverse(ct, pos, self._hug_dir):
                chosen = self._hug_dir
                # After each successful move, turn left to re-hug the wall
                self._hug_dir = self._hug_dir.rotate_left()
                self._hug_steps += 1
                return chosen
            self._hug_dir = self._hug_dir.rotate_right()

        # Completely surrounded
        self.target = self._pick_target()
        self._reset_hug()
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _can_traverse(self, ct: Controller, pos: Position, direction: Direction) -> bool:
        """
        A tile is traversable if it either already has a road/conveyor/core
        (can_move returns True) or is EMPTY (we can build a road there).
        Walls and ore tiles are not traversable for general navigation.
        """
        if ct.can_move(direction):
            return True
        neighbour = pos.add(direction)
        if not ct.is_in_vision(neighbour):
            return False
        env = ct.get_tile_env(neighbour)
        return env == Environment.EMPTY

    @staticmethod
    def _dir_preference(ideal: Direction) -> list[Direction]:
        """Ideal direction first, then the two ±45° neighbours."""
        return [ideal, ideal.rotate_left(), ideal.rotate_right()]

    @staticmethod
    def _dist_sq(x1: int, y1: int, x2: int, y2: int) -> int:
        return (x1 - x2) ** 2 + (y1 - y2) ** 2

    def _reset_hug(self) -> None:
        self._hugging = False
        self._hug_dir = None
        self._hug_start_dist = None
        self._hug_steps = 0
