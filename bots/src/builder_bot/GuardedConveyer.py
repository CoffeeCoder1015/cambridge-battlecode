from collections import deque
import sys

from cambc import Controller, Direction, EntityType, Environment, Position


CARDINAL_DIRECTIONS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)


class GuardedConveyer:
    def __init__(self) -> None:
        self.path: list[Direction] = []
        self.ore_target: Position | None = None
        self.last_known_ore: Position | None = None
        self.step_index = 0
        self.complete = False

    def run(self, ct: Controller, nearby_tiles: list[Position]) -> tuple[bool, bool]:
        """
        Returns:
            (acted_this_round, failed_plan)
        """
        self._log(
            ct,
            (
                f"run start: complete={self.complete}, "
                f"target={self.ore_target}, step={self.step_index}/{len(self.path)}"
            ),
        )

        if self.complete:
            self._log(ct, "already complete, nothing to do")
            return False, False

        if self.ore_target is None:
            self._log(ct, "no target yet, planning from core")
            if not self._plan_from_core(ct, nearby_tiles):
                # Planning failure is transient: keep scanning every round.
                self._log(ct, "planning failed this round, will retry next round")
                return False, False

        acted, failed = self._execute_plan(ct)
        if failed:
            # Drop this plan and retry fresh planning on future rounds.
            self._log(ct, "execution failed, clearing plan and retrying in future rounds")
            self.path = []
            self.ore_target = None
            self.step_index = 0
            return acted, False
        self._log(ct, f"execution result: acted={acted}, failed={failed}")
        return acted, False

    def _plan_from_core(self, ct: Controller, nearby_tiles: list[Position]) -> bool:
        my_pos = ct.get_position()
        if not self._is_on_friendly_core(ct, my_pos):
            self._log(ct, f"plan rejected: not standing on friendly core at {my_pos}")
            return False

        ore_tiles = self._visible_ore_tiles(ct, nearby_tiles)
        if not ore_tiles:
            self._log(ct, "plan rejected: no visible ore in current vision scan")
            return False
        self._log(ct, f"planning with {len(ore_tiles)} visible ore tile(s)")

        best_ore: Position | None = None
        best_path: list[Direction] | None = None

        for ore_pos in ore_tiles:
            candidate = self._path_to_adjacent_tile(
                ct=ct,
                nearby_tiles=nearby_tiles,
                start=my_pos,
                ore_pos=ore_pos,
                max_steps=8,
            )
            if candidate is None:
                self._log(ct, f"no <=8 cardinal path to adjacent tile for ore {ore_pos}")
                continue
            self._log(ct, f"candidate path to ore {ore_pos}: len={len(candidate)}")
            if best_path is None or len(candidate) < len(best_path):
                best_path = candidate
                best_ore = ore_pos

        if best_path is None or best_ore is None:
            self._log(ct, "plan rejected: no ore had a valid <=8-move path")
            return False

        self.path = best_path
        self.ore_target = best_ore
        self.last_known_ore = best_ore
        self.step_index = 0
        self._log(
            ct,
            f"plan selected: ore={self.ore_target}, path_len={len(self.path)}, path={self.path}",
        )
        return True

    def _execute_plan(self, ct: Controller) -> tuple[bool, bool]:
        if self.ore_target is None:
            self._log(ct, "execute failed: ore_target is None")
            return False, True

        my_pos = ct.get_position()

        if self._is_adjacent_cardinal(my_pos, self.ore_target):
            self._log(ct, f"adjacent to ore {self.ore_target}, attempting final build")
            built = self._try_build_generator(ct)
            self._log(ct, f"final build result: built={built}")
            return built, False

        if self.step_index >= len(self.path):
            self._log(
                ct,
                f"execute failed: step_index {self.step_index} >= path_len {len(self.path)}",
            )
            return False, True

        move_dir = self.path[self.step_index]
        next_pos = my_pos.add(move_dir)
        acted = False
        self._log(ct, f"step {self.step_index}: {my_pos} -> {next_pos} via {move_dir}")

        acted = self._prepare_and_place_conveyor(ct, next_pos, move_dir) or acted

        if ct.can_move(move_dir):
            ct.move(move_dir)
            self.step_index += 1
            self._log(ct, f"moved {move_dir}; new step_index={self.step_index}")
            return True, False

        self._log(ct, f"cannot move {move_dir} this round")
        return acted, False

    def _path_to_adjacent_tile(
        self,
        ct: Controller,
        nearby_tiles: list[Position],
        start: Position,
        ore_pos: Position,
        max_steps: int,
    ) -> list[Direction] | None:
        visible = {(p.x, p.y) for p in nearby_tiles}
        visible.add((start.x, start.y))

        visited: set[tuple[int, int]] = {(start.x, start.y)}
        queue: deque[tuple[Position, list[Direction]]] = deque([(start, [])])

        while queue:
            cur_pos, cur_path = queue.popleft()

            if self._is_adjacent_cardinal(cur_pos, ore_pos):
                return cur_path

            if len(cur_path) >= max_steps:
                continue

            for move_dir in CARDINAL_DIRECTIONS:
                next_pos = cur_pos.add(move_dir)
                key = (next_pos.x, next_pos.y)
                if key in visited or key not in visible:
                    continue
                if not self._is_traversable_for_plan(ct, next_pos):
                    continue
                visited.add(key)
                queue.append((next_pos, cur_path + [move_dir]))

        return None

    def _visible_ore_tiles(self, ct: Controller, nearby_tiles: list[Position]) -> list[Position]:
        ores: list[Position] = []
        for tile in nearby_tiles:
            try:
                env = ct.get_tile_env(tile)
            except Exception:
                continue
            if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                ores.append(tile)
        return ores

    def _is_traversable_for_plan(self, ct: Controller, pos: Position) -> bool:
        try:
            env = ct.get_tile_env(pos)
        except Exception:
            return False

        if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            return False

        bot_id = ct.get_tile_builder_bot_id(pos)
        if bot_id is not None and bot_id != ct.get_id():
            return False

        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return True

        b_team = ct.get_team(building_id)
        b_type = ct.get_entity_type(building_id)

        if b_type == EntityType.CORE:
            return b_team == ct.get_team()

        return b_team == ct.get_team() and b_type in (
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.ROAD,
        )

    def _is_on_friendly_core(self, ct: Controller, pos: Position) -> bool:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        return (
            ct.get_entity_type(building_id) == EntityType.CORE
            and ct.get_team(building_id) == ct.get_team()
        )

    def _try_build_generator(self, ct: Controller) -> bool:
        if self.ore_target is None:
            self._log(ct, "build failed: ore_target is None")
            return False

        # Remember ore coordinates even if local plan state changes.
        self.last_known_ore = self.ore_target

        cleared = self._clear_ore_obstruction(ct, self.ore_target)
        if cleared:
            self._log(ct, f"cleared obstruction on ore tile {self.ore_target}")

        if ct.get_action_cooldown() != 0:
            self._log(ct, f"build delayed: action_cd={ct.get_action_cooldown()}")
            return cleared

        if ct.can_build_harvester(self.ore_target):
            ct.build_harvester(self.ore_target)
            self.complete = True
            self._log(ct, f"built harvester at {self.ore_target}")
            return True
        self._log(ct, f"cannot build harvester at {self.ore_target}")

        can_build_generator = getattr(ct, "can_build_generator", None)
        build_generator = getattr(ct, "build_generator", None)
        if callable(can_build_generator) and callable(build_generator):
            if can_build_generator(self.ore_target):
                build_generator(self.ore_target)
                self.complete = True
                self._log(ct, f"built generator at {self.ore_target}")
                return True
            self._log(ct, f"generator API exists but cannot build at {self.ore_target}")
        else:
            self._log(ct, "generator API not present on controller, skipping generator build")

        return cleared

    def _prepare_and_place_conveyor(
        self,
        ct: Controller,
        target_pos: Position,
        move_dir: Direction,
    ) -> bool:
        """
        Ensures conveyor tile is clean (roads/markers/wrong-direction conveyor),
        then places the expected conveyor when possible.
        """
        acted = False
        desired_dir = move_dir.opposite()

        building_id = ct.get_tile_building_id(target_pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            b_team = ct.get_team(building_id)
            my_team = ct.get_team()

            if b_type == EntityType.CORE:
                self._log(ct, f"target tile {target_pos} is core; skipping conveyor placement")
                return acted

            if b_team == my_team:
                if b_type == EntityType.ROAD:
                    if ct.can_destroy(target_pos):
                        ct.destroy(target_pos)
                        acted = True
                        self._log(ct, f"destroyed road at {target_pos} before conveyor placement")
                elif b_type == EntityType.CONVEYOR:
                    try:
                        current_dir = ct.get_direction(building_id)
                    except Exception:
                        current_dir = None
                    if current_dir != desired_dir and ct.can_destroy(target_pos):
                        ct.destroy(target_pos)
                        acted = True
                        self._log(
                            ct,
                            (
                                f"destroyed misaligned conveyor at {target_pos}; "
                                f"had={current_dir}, want={desired_dir}"
                            ),
                        )

        marker_id = self._find_marker_at(ct, target_pos)
        if marker_id is not None:
            if ct.can_destroy(target_pos):
                ct.destroy(target_pos)
                acted = True
                self._log(ct, f"destroyed marker at {target_pos} before conveyor placement")
            else:
                self._log(ct, f"marker at {target_pos} is not destroyable this round")

        # If the expected conveyor already exists, no need to place again.
        building_id = ct.get_tile_building_id(target_pos)
        if building_id is not None and ct.get_entity_type(building_id) == EntityType.CONVEYOR:
            try:
                if ct.get_direction(building_id) == desired_dir:
                    return acted
            except Exception:
                pass

        if ct.get_action_cooldown() == 0 and ct.can_build_conveyor(target_pos, desired_dir):
            ct.build_conveyor(target_pos, desired_dir)
            acted = True
            self._log(ct, f"built conveyor at {target_pos} facing {desired_dir}")
        else:
            self._log(
                ct,
                (
                    f"could not build conveyor at {target_pos}; "
                    f"action_cd={ct.get_action_cooldown()}"
                ),
            )

        return acted

    def _clear_ore_obstruction(self, ct: Controller, ore_pos: Position) -> bool:
        acted = False

        building_id = ct.get_tile_building_id(ore_pos)
        if building_id is not None:
            b_team = ct.get_team(building_id)
            b_type = ct.get_entity_type(building_id)
            if b_team == ct.get_team():
                if ct.can_destroy(ore_pos):
                    ct.destroy(ore_pos)
                    acted = True
                    self._log(ct, f"destroyed allied {b_type} on ore tile {ore_pos}")
                else:
                    self._log(ct, f"allied {b_type} on ore tile {ore_pos} cannot be destroyed now")
            else:
                self._log(ct, f"enemy {b_type} blocks ore tile {ore_pos}; cannot clear")

        marker_id = self._find_marker_at(ct, ore_pos)
        if marker_id is not None:
            if ct.can_destroy(ore_pos):
                ct.destroy(ore_pos)
                acted = True
                self._log(ct, f"destroyed marker on ore tile {ore_pos}")
            else:
                self._log(ct, f"marker on ore tile {ore_pos} is not destroyable")

        return acted

    @staticmethod
    def _find_marker_at(ct: Controller, pos: Position) -> int | None:
        for entity_id in ct.get_nearby_entities():
            if ct.get_entity_type(entity_id) != EntityType.MARKER:
                continue
            if ct.get_position(entity_id) == pos:
                return entity_id
        return None

    @staticmethod
    def _is_adjacent_cardinal(a: Position, b: Position) -> bool:
        return abs(a.x - b.x) + abs(a.y - b.y) == 1

    @staticmethod
    def _log(ct: Controller, msg: str) -> None:
        if ct.get_current_round() >= 100:
            return
        print(
            f"[GC id={ct.get_id()} r={ct.get_current_round()}] {msg}",
            file=sys.stderr,
        )
