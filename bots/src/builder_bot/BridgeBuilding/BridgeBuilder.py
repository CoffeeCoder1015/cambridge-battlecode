from typing import Any, Callable

from cambc import Controller, Direction, EntityType, Environment, Position
from ..Movement.TangentBug import TangentBug

ORE_ENVS = (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)
ACTION_RADIUS_SQ = 4
MAX_GREEDY_MOVES = 7  # strictly less than 8


class BridgeBuilder:
    def __init__(self) -> None:
        self.ore_target: tuple[int, int] | None = None
        self._post_generator_bridge_pending = False
        self._post_bridge_target: tuple[int, int] | None = None
        self._post_bridge_nav = TangentBug()

    def main(
        self,
        ct: Controller,
        known_symmetry=None,
        core_pos: tuple[int, int] | None = None,
        symmetry_analyzer: Any | None = None,
        bfs_builder=None,
        nav=None,
        set_nav_target: Callable[[int, int], None] | None = None,
    ) -> bool:
        del known_symmetry

        if self._post_bridge_target is not None:
            return self._advance_post_bridge_navigation(ct)

        if self._post_generator_bridge_pending:
            return self._run_post_generator_bridge(ct, core_pos)

        my_pos = ct.get_position()
        visible_ores = self._visible_ores_from_scan(ct, symmetry_analyzer)

        if self.ore_target is not None:
            if self.ore_target not in visible_ores:
                self.ore_target = None

        if self.ore_target is None:
            self.ore_target = self._select_reachable_ore(ct, my_pos, visible_ores)

        if self.ore_target is None:
            return self._run_bfs_fallback(
                ct=ct,
                core_pos=core_pos,
                bfs_builder=bfs_builder,
                nav=nav,
                set_nav_target=set_nav_target,
            )

        ore_pos = Position(self.ore_target[0], self.ore_target[1])

        if self._in_action_radius(my_pos, ore_pos):
            built = self._build_generator_on_ore(ct, ore_pos)
            if built:
                self.ore_target = None
                self._post_generator_bridge_pending = True
            # Keep control while in range so fallback movement does not pull us off target.
            return True

        path = self._greedy_path_to_ore(ct, my_pos, ore_pos, MAX_GREEDY_MOVES)
        if path is None:
            self.ore_target = None
            return self._run_bfs_fallback(
                ct=ct,
                core_pos=core_pos,
                bfs_builder=bfs_builder,
                nav=nav,
                set_nav_target=set_nav_target,
            )

        if not path:
            return True

        self._road_then_move(ct, path[0])
        return True

    def _visible_ores_from_scan(self, ct: Controller, symmetry_analyzer: Any | None) -> set[tuple[int, int]]:
        visible: set[tuple[int, int]] = set()
        map_history = getattr(symmetry_analyzer, "map_history", None)
        if isinstance(map_history, dict):
            for (x, y), env in map_history.items():
                if env not in ORE_ENVS:
                    continue
                ore_pos = Position(x, y)
                if ct.is_in_vision(ore_pos):
                    visible.add((x, y))
            return visible

        # Fallback if scan state is unavailable.
        for tile in ct.get_nearby_tiles():
            try:
                env = ct.get_tile_env(tile)
            except Exception:
                continue
            if env in ORE_ENVS:
                visible.add((tile.x, tile.y))
        return visible

    def _select_reachable_ore(
        self,
        ct: Controller,
        my_pos: Position,
        visible_ores: set[tuple[int, int]],
    ) -> tuple[int, int] | None:
        best_target: tuple[int, int] | None = None
        best_len: int | None = None

        for ox, oy in visible_ores:
            ore_pos = Position(ox, oy)
            path = self._greedy_path_to_ore(ct, my_pos, ore_pos, MAX_GREEDY_MOVES)
            if path is None:
                continue
            path_len = len(path)
            if best_len is None or path_len < best_len:
                best_len = path_len
                best_target = (ox, oy)

        return best_target

    def _greedy_path_to_ore(
        self,
        ct: Controller,
        start: Position,
        ore_pos: Position,
        max_moves: int,
    ) -> list[Direction] | None:
        if self._in_action_radius(start, ore_pos):
            return []

        cur = Position(start.x, start.y)
        path: list[Direction] = []
        visited: set[tuple[int, int]] = {(cur.x, cur.y)}

        for _ in range(max_moves):
            best_dir: Direction | None = None
            best_dist_sq: int | None = None

            base = cur.direction_to(ore_pos)
            for move_dir in self._candidate_dirs(base):
                nxt = cur.add(move_dir)
                nxt_key = (nxt.x, nxt.y)
                if nxt_key in visited:
                    continue
                if not self._is_step_candidate(ct, nxt):
                    continue
                dist_sq = (nxt.x - ore_pos.x) ** 2 + (nxt.y - ore_pos.y) ** 2
                if best_dist_sq is None or dist_sq < best_dist_sq:
                    best_dist_sq = dist_sq
                    best_dir = move_dir

            if best_dir is None:
                return None

            cur = cur.add(best_dir)
            path.append(best_dir)
            visited.add((cur.x, cur.y))

            if self._in_action_radius(cur, ore_pos):
                return path

        return None

    @staticmethod
    def _candidate_dirs(base: Direction) -> tuple[Direction, ...]:
        if base == Direction.CENTRE:
            return tuple(d for d in Direction if d != Direction.CENTRE)

        dirs = [base]
        r = base
        l = base
        for _ in range(3):
            r = r.rotate_right()
            l = l.rotate_left()
            dirs.append(r)
            dirs.append(l)
        dirs.append(base.opposite())

        seen: set[Direction] = set()
        ordered: list[Direction] = []
        for d in dirs:
            if d == Direction.CENTRE or d in seen:
                continue
            seen.add(d)
            ordered.append(d)
        return tuple(ordered)

    def _is_step_candidate(self, ct: Controller, pos: Position) -> bool:
        if not (0 <= pos.x < ct.get_map_width() and 0 <= pos.y < ct.get_map_height()):
            return False
        if not ct.is_in_vision(pos):
            return False

        try:
            env = ct.get_tile_env(pos)
        except Exception:
            return False
        if env == Environment.WALL:
            return False

        building_id = ct.get_tile_building_id(pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            if b_type in (EntityType.ROAD, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                pass
            elif b_type == EntityType.CORE:
                if ct.get_team(building_id) != ct.get_team():
                    return False
            else:
                return False

        bot_id = ct.get_tile_builder_bot_id(pos)
        if bot_id is not None and bot_id != ct.get_id():
            return False

        return True

    @staticmethod
    def _in_action_radius(my_pos: Position, target: Position) -> bool:
        dx = my_pos.x - target.x
        dy = my_pos.y - target.y
        return dx * dx + dy * dy <= ACTION_RADIUS_SQ

    def _build_generator_on_ore(self, ct: Controller, ore_pos: Position) -> bool:
        if ct.get_action_cooldown() != 0:
            return False

        can_build_generator = getattr(ct, "can_build_generator", None)
        build_generator = getattr(ct, "build_generator", None)
        if callable(can_build_generator) and callable(build_generator):
            if can_build_generator(ore_pos):
                build_generator(ore_pos)
                return True

        # Backward-compatible fallback where ore extraction uses harvester API.
        if ct.can_build_harvester(ore_pos):
            ct.build_harvester(ore_pos)
            return True

        return False

    def _run_post_generator_bridge(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
    ) -> bool:
        if core_pos is None:
            return True

        if ct.get_action_cooldown() != 0:
            return True

        start_pos = ct.get_position()
        target_pos = self._select_bridge_target_toward_core(
            ct=ct,
            start_pos=start_pos,
            core_pos=core_pos,
        )
        if target_pos is None:
            self._post_generator_bridge_pending = False
            return True

        if ct.can_build_bridge(start_pos, target_pos):
            ct.build_bridge(start_pos, target_pos)
            self._post_generator_bridge_pending = False
            self._start_post_bridge_navigation(target_pos)
            self._advance_post_bridge_navigation(ct)
            return True

        # Some tiles (for example roads) can block bridge placement on the start tile.
        if self._clear_underfoot_for_bridge(ct, start_pos):
            if ct.can_build_bridge(start_pos, target_pos):
                ct.build_bridge(start_pos, target_pos)
                self._post_generator_bridge_pending = False
                self._start_post_bridge_navigation(target_pos)
                self._advance_post_bridge_navigation(ct)
                return True

        return True

    def _start_post_bridge_navigation(self, target_pos: Position) -> None:
        self._post_bridge_target = (target_pos.x, target_pos.y)
        self._post_bridge_nav.set_target(target_pos.x, target_pos.y)

    def _advance_post_bridge_navigation(self, ct: Controller) -> bool:
        if self._post_bridge_target is None:
            return True

        tx, ty = self._post_bridge_target
        my_pos = ct.get_position()
        if (my_pos.x, my_pos.y) == (tx, ty):
            self._post_bridge_target = None
            self._post_bridge_nav.reset()
            return True

        if self._post_bridge_nav.target != (tx, ty):
            self._post_bridge_nav.set_target(tx, ty)

        move_dir = self._post_bridge_nav.next_move(ct)
        if move_dir is None:
            return True

        self._road_then_move(ct, move_dir)

        new_pos = ct.get_position()
        if (new_pos.x, new_pos.y) == (tx, ty):
            self._post_bridge_target = None
            self._post_bridge_nav.reset()
        return True

    def _select_bridge_target_toward_core(
        self,
        ct: Controller,
        start_pos: Position,
        core_pos: tuple[int, int],
    ) -> Position | None:
        core = Position(core_pos[0], core_pos[1])
        candidates: list[Position] = []

        for dx in range(-3, 4):
            for dy in range(-3, 4):
                dist_from_start_sq = dx * dx + dy * dy
                if dist_from_start_sq == 0 or dist_from_start_sq > 9:
                    continue
                x = start_pos.x + dx
                y = start_pos.y + dy
                if not (0 <= x < ct.get_map_width() and 0 <= y < ct.get_map_height()):
                    continue
                candidates.append(Position(x, y))

        if not candidates:
            return None

        def sort_key(pos: Position) -> tuple[int, int, int, int]:
            core_dist_sq = (pos.x - core.x) ** 2 + (pos.y - core.y) ** 2
            start_dist_sq = (pos.x - start_pos.x) ** 2 + (pos.y - start_pos.y) ** 2
            return (core_dist_sq, -start_dist_sq, pos.x, pos.y)

        candidates.sort(key=sort_key)
        return candidates[0]

    @staticmethod
    def _clear_underfoot_for_bridge(ct: Controller, my_pos: Position) -> bool:
        building_id = ct.get_tile_building_id(my_pos)
        if building_id is None:
            return False

        b_type = ct.get_entity_type(building_id)
        if b_type == EntityType.CORE:
            return False

        if b_type in (
            EntityType.ROAD,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BARRIER,
        ) and ct.can_destroy(my_pos):
            ct.destroy(my_pos)
            return True

        return False

    @staticmethod
    def _road_then_move(ct: Controller, move_dir: Direction) -> bool:
        acted = False
        move_pos = ct.get_position().add(move_dir)
        if not ct.is_tile_passable(move_pos):
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

    @staticmethod
    def _run_bfs_fallback(
        ct: Controller,
        core_pos: tuple[int, int] | None,
        bfs_builder,
        nav,
        set_nav_target: Callable[[int, int], None] | None,
    ) -> bool:
        if bfs_builder is None or nav is None or set_nav_target is None:
            return False
        return bfs_builder.run(
            ct=ct,
            core_pos=core_pos,
            nav=nav,
            set_nav_target=set_nav_target,
        )
