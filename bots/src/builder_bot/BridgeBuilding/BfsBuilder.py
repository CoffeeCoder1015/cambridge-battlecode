from collections import deque

from cambc import Controller, EntityType


class BfsBuilder:
    def __init__(self) -> None:
        self._root: tuple[int, int] | None = None
        self._order: list[tuple[int, int]] = []
        self._idx = 0
        self._active_target: tuple[int, int] | None = None

    def run(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
        nav,
        set_nav_target,
    ) -> bool:
        if core_pos is None:
            return False

        if self._root != core_pos or not self._order:
            self._reset_for_core(ct, core_pos)

        my_pos = ct.get_position()
        my_xy = (my_pos.x, my_pos.y)

        # Advance through already-reached BFS nodes.
        while self._idx < len(self._order) and self._order[self._idx] == my_xy:
            self._idx += 1
            self._active_target = None

        if self._idx >= len(self._order):
            return False

        target = self._order[self._idx]
        if self._active_target != target:
            set_nav_target(target[0], target[1])
            self._active_target = target

        acted = self._road_then_nav_step(ct, nav)
        if not acted:
            # If we cannot progress to this node this round, skip it and continue BFS.
            self._idx += 1
            self._active_target = None
            return False

        new_pos = ct.get_position()
        if (new_pos.x, new_pos.y) == target:
            self._idx += 1
            self._active_target = None

        return True

    def _reset_for_core(self, ct: Controller, core_pos: tuple[int, int]) -> None:
        self._root = core_pos
        self._idx = 0
        self._active_target = None
        self._order = self._build_bfs_order(
            root=core_pos,
            width=ct.get_map_width(),
            height=ct.get_map_height(),
        )

    def _build_bfs_order(
        self,
        root: tuple[int, int],
        width: int,
        height: int,
    ) -> list[tuple[int, int]]:
        queue: deque[tuple[int, int]] = deque([root])
        visited: set[tuple[int, int]] = {root}
        order: list[tuple[int, int]] = []

        # All movement directions are considered valid for expansion.
        neighbor_deltas = (
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        )

        while queue:
            cx, cy = queue.popleft()
            order.append((cx, cy))
            for dx, dy in neighbor_deltas:
                nx, ny = cx + dx, cy + dy
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                nxt = (nx, ny)
                if nxt in visited:
                    continue
                visited.add(nxt)
                queue.append(nxt)

        root_x, root_y = root
        order.sort(
            key=lambda p: (
                -max(abs(p[0] - root_x), abs(p[1] - root_y)),
                p[0],
                p[1],
            )
        )
        return order

    @staticmethod
    def _road_then_nav_step(ct: Controller, nav) -> bool:
        move_dir = nav.next_move(ct)
        if move_dir is None:
            return False

        acted = False
        move_pos = ct.get_position().add(move_dir)
        has_friendly_marker = any(
            ct.get_entity_type(eid) == EntityType.MARKER
            and ct.get_team(eid) == ct.get_team()
            and ct.get_position(eid) == move_pos
            for eid in ct.get_nearby_entities()
        )
        if ct.can_build_road(move_pos) and not has_friendly_marker:
            ct.build_road(move_pos)
            acted = True

        if ct.can_move(move_dir):
            ct.move(move_dir)
            acted = True

        return acted
