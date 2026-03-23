from collections import deque
import sys

from cambc import Controller, Direction, EntityType, Environment, Position


CARDINAL_DIRECTIONS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)

DEBUG_PRINTS = False


class GuardedConveyer:
    def __init__(self) -> None:
        self.path: list[Direction] = []
        self.ore_target: Position | None = None
        self.last_known_ore: Position | None = None
        self.step_index = 0
        self.complete = False
        self.no_ore_in_scan = False
        self.was_on_core_last_turn = False
        self.pending_underfoot_core_link = False
        self.ore_finalize_phase: str | None = None
        self.retreat_conveyor_tile: Position | None = None

    def run(self, ct: Controller, nearby_tiles: list[Position]) -> tuple[bool, bool]:
        """
        Returns:
            (acted_this_round, failed_plan)
        """
        my_pos = ct.get_position()
        on_core_now = self._is_on_friendly_core(ct, my_pos)
        had_core_last_turn = self.was_on_core_last_turn

        self.no_ore_in_scan = False
        self._log(
            ct,
            (
                f"run start: complete={self.complete}, target={self.ore_target}, "
                f"step={self.step_index}/{len(self.path)}, on_core_now={on_core_now}, "
                f"was_on_core_last_turn={had_core_last_turn}"
            ),
        )

        if self.complete:
            self._log(ct, "already complete, nothing to do")
            return self._finish_turn(on_core_now, False, False)

        if self.ore_target is None:
            self.no_ore_in_scan = len(self._visible_ore_tiles(ct, nearby_tiles)) == 0
            self._log(ct, "no target yet, planning from core")
            if not self._plan_from_core(ct, nearby_tiles, on_core_now, had_core_last_turn):
                # Planning failure is transient: keep scanning every round.
                self._log(ct, "planning failed this round, will retry next round")
                return self._finish_turn(on_core_now, False, False)

            if had_core_last_turn and not on_core_now:
                self.pending_underfoot_core_link = True

        if self.pending_underfoot_core_link:
            acted, done = self._swap_underfoot_to_core_conveyor(ct)
            if done:
                self.pending_underfoot_core_link = False
            # Spend this turn linking underfoot tile to the core.
            return self._finish_turn(on_core_now, True, False)

        acted, failed = self._execute_plan(ct)
        if failed:
            # Drop this plan and retry fresh planning on future rounds.
            self._log(ct, "execution failed, clearing plan and retrying in future rounds")
            self.path = []
            self.ore_target = None
            self.step_index = 0
            self.pending_underfoot_core_link = False
            self.ore_finalize_phase = None
            self.retreat_conveyor_tile = None
            return self._finish_turn(on_core_now, acted, False)
        self._log(ct, f"execution result: acted={acted}, failed={failed}")
        return self._finish_turn(on_core_now, acted, False)

    def _plan_from_core(
        self,
        ct: Controller,
        nearby_tiles: list[Position],
        on_core_now: bool,
        had_core_last_turn: bool,
    ) -> bool:
        my_pos = ct.get_position()
        if not on_core_now and not had_core_last_turn:
            self._log(
                ct,
                f"plan rejected: not on core now and was not on core last turn at {my_pos}",
            )
            return False

        ore_tiles = self._visible_ore_tiles(ct, nearby_tiles)
        if not ore_tiles:
            self.no_ore_in_scan = True
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
        self.ore_finalize_phase = None
        self.retreat_conveyor_tile = None
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

        if self.ore_finalize_phase is not None:
            return self._run_ore_finalize_sequence(ct)

        if self._is_adjacent_cardinal(my_pos, self.ore_target):
            self.retreat_conveyor_tile = my_pos
            self.ore_finalize_phase = "STEP_ONTO_ORE"
            self._log(
                ct,
                (
                    f"adjacent to ore {self.ore_target}; starting finalize sequence "
                    "(step onto ore -> fortify ring -> retreat -> build)"
                ),
            )
            return self._run_ore_finalize_sequence(ct)

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

    def _run_ore_finalize_sequence(self, ct: Controller) -> tuple[bool, bool]:
        if self.ore_target is None:
            self._log(ct, "finalize failed: ore_target missing")
            return False, True

        my_pos = ct.get_position()
        ore_pos = self.ore_target

        if self.ore_finalize_phase == "STEP_ONTO_ORE":
            if my_pos == ore_pos:
                self.ore_finalize_phase = "FORTIFY_RING"
                self._log(ct, f"finalize: arrived on ore tile {ore_pos}")
                return False, False

            # Requirement: place a road on ore before stepping onto it.
            prepared, done = self._prepare_ore_tile_for_step(ct, ore_pos)
            if prepared:
                return True, False
            if not done:
                return False, False

            step_dir = my_pos.direction_to(ore_pos)
            if step_dir in CARDINAL_DIRECTIONS and ct.can_move(step_dir):
                ct.move(step_dir)
                self._log(ct, f"finalize: moved onto ore via {step_dir}")
                return True, False

            self._log(
                ct,
                f"finalize: waiting to step onto ore {ore_pos}; can_move={ct.can_move(step_dir) if step_dir in CARDINAL_DIRECTIONS else False}",
            )
            return False, False

        if self.ore_finalize_phase == "FORTIFY_RING":
            acted, done = self._fortify_ore_ring(ct, ore_pos)
            if acted:
                return True, False
            if not done:
                return False, False
            self.ore_finalize_phase = "RETREAT_TO_CONVEYOR"
            self._log(ct, "finalize: ore ring fortification complete")
            return False, False

        if self.ore_finalize_phase == "RETREAT_TO_CONVEYOR":
            if self.retreat_conveyor_tile is None:
                self._log(ct, "finalize: retreat tile missing, cannot continue")
                return False, True

            if my_pos == self.retreat_conveyor_tile:
                self.ore_finalize_phase = "BUILD_GENERATOR"
                self._log(ct, f"finalize: retreated to conveyor tile {my_pos}")
                return False, False

            step_dir = my_pos.direction_to(self.retreat_conveyor_tile)
            if step_dir in CARDINAL_DIRECTIONS and ct.can_move(step_dir):
                ct.move(step_dir)
                self._log(ct, f"finalize: retreat moved {step_dir} to conveyor tile")
                return True, False

            self._log(ct, "finalize: retreat blocked this round")
            return False, False

        if self.ore_finalize_phase == "BUILD_GENERATOR":
            cleared, done = self._clear_road_on_ore(ct, ore_pos)
            if cleared:
                return True, False
            if not done:
                return False, False

            built = self._try_build_generator(ct)
            self._log(ct, f"finalize: build result={built}")
            if built and self.complete:
                self.complete = False
                self.ore_finalize_phase = "BACKFILL_TO_CORE"
                self._log(ct, "finalize: generator built, starting conveyor backfill to core")
            return built, False

        if self.ore_finalize_phase == "BACKFILL_TO_CORE":
            if self._is_on_friendly_core(ct, my_pos):
                self.ore_finalize_phase = None
                self.complete = True
                if DEBUG_PRINTS:
                    print("done!", file=sys.stderr)
                return False, False

            acted, done = self._fortify_backfill_ring(ct, my_pos)
            if acted:
                return True, False
            if not done:
                return False, False

            move_dir = self._underfoot_conveyor_direction(ct, my_pos)
            if move_dir is None:
                core_adj = self._adjacent_cardinal_core_tile(ct, my_pos)
                if core_adj is not None:
                    step_dir = my_pos.direction_to(core_adj)
                    if step_dir in CARDINAL_DIRECTIONS and ct.can_move(step_dir):
                        ct.move(step_dir)
                        self._log(ct, f"backfill: moved directly onto core via {step_dir}")
                        return True, False
                self._log(ct, "backfill: no conveyor direction underfoot; waiting")
                return False, False

            if ct.can_move(move_dir):
                ct.move(move_dir)
                self._log(ct, f"backfill: moved along underfoot conveyor direction {move_dir}")
                return True, False

            self._log(ct, f"backfill: cannot move in conveyor direction {move_dir}")
            return False, False

        self._log(ct, f"finalize: unknown phase {self.ore_finalize_phase}")
        return False, True

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

    def _fortify_ore_ring(self, ct: Controller, ore_pos: Position) -> tuple[bool, bool]:
        """
        Build barriers on all 8 neighboring tiles around ore.
        Only target ROAD, MARKER, EMPTY, and ORE tiles.
        Natural walls or other structures are treated as already acceptable.
        """
        unresolved = False
        for target in self._ore_ring_positions(ore_pos):
            if not self._is_in_bounds(ct, target):
                continue
            if self.retreat_conveyor_tile is not None and target == self.retreat_conveyor_tile:
                continue

            marker_id = self._find_marker_at(ct, target)
            if marker_id is not None:
                unresolved = True
                if ct.can_destroy(target):
                    ct.destroy(target)
                    self._log(ct, f"fortify: destroyed marker at {target}")
                    return True, False
                self._log(ct, f"fortify: marker at {target} not destroyable")
                continue

            building_id = ct.get_tile_building_id(target)
            if building_id is not None:
                b_type = ct.get_entity_type(building_id)
                if b_type == EntityType.ROAD:
                    unresolved = True
                    if ct.can_destroy(target):
                        ct.destroy(target)
                        self._log(ct, f"fortify: destroyed road at {target}")
                        return True, False
                    self._log(ct, f"fortify: road at {target} not destroyable")
                    continue

                if b_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                    continue
                # Non-road structures (barriers/core/harvesters/etc.) are left as-is.
                continue

            env = ct.get_tile_env(target)
            if env in (
                Environment.EMPTY,
                Environment.ORE_TITANIUM,
                Environment.ORE_AXIONITE,
            ):
                unresolved = True
                if ct.get_action_cooldown() == 0 and ct.can_build_barrier(target):
                    ct.build_barrier(target)
                    self._log(ct, f"fortify: built barrier at {target}")
                    return True, False

                if ct.get_action_cooldown() != 0:
                    self._log(ct, f"fortify: waiting action cooldown for {target}")
                    return False, False

        if unresolved:
            return False, False
        return False, True

    def _prepare_ore_tile_for_step(self, ct: Controller, ore_pos: Position) -> tuple[bool, bool]:
        """
        Ensure ore tile has a road before stepping onto it.
        Clears non-road blockers first (but preserves conveyors).
        Returns (acted, done).
        """
        building_id = ct.get_tile_building_id(ore_pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            b_team = ct.get_team(building_id)

            if b_type == EntityType.ROAD and b_team == ct.get_team():
                return False, True

            if b_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                self._log(ct, f"step-on-ore blocked by conveyor at {ore_pos}; cannot replace")
                return False, False

            if ct.can_destroy(ore_pos):
                ct.destroy(ore_pos)
                self._log(ct, f"step-on-ore: destroyed {b_type} at {ore_pos}")
                return True, False

            self._log(ct, f"step-on-ore: cannot destroy {b_type} at {ore_pos}")
            return False, False

        marker_id = self._find_marker_at(ct, ore_pos)
        if marker_id is not None:
            if ct.can_destroy(ore_pos):
                ct.destroy(ore_pos)
                self._log(ct, f"step-on-ore: destroyed marker at {ore_pos}")
                return True, False
            self._log(ct, f"step-on-ore: marker at {ore_pos} not destroyable")
            return False, False

        if ct.get_action_cooldown() == 0 and ct.can_build_road(ore_pos):
            ct.build_road(ore_pos)
            self._log(ct, f"step-on-ore: built road at {ore_pos}")
            return True, False

        self._log(
            ct,
            f"step-on-ore: waiting to build road at {ore_pos}; action_cd={ct.get_action_cooldown()}",
        )
        return False, False

    def _clear_road_on_ore(self, ct: Controller, ore_pos: Position) -> tuple[bool, bool]:
        """
        Before final generator build, remove road on ore if present.
        Returns (acted, done).
        """
        building_id = ct.get_tile_building_id(ore_pos)
        if building_id is None:
            return False, True

        b_type = ct.get_entity_type(building_id)
        b_team = ct.get_team(building_id)
        if b_type != EntityType.ROAD:
            return False, True

        if b_team != ct.get_team():
            self._log(ct, f"build-phase: enemy road on ore at {ore_pos}; cannot clear")
            return False, False

        if ct.can_destroy(ore_pos):
            ct.destroy(ore_pos)
            self._log(ct, f"build-phase: cleared road on ore at {ore_pos}")
            return True, False

        self._log(ct, f"build-phase: road on ore at {ore_pos} not destroyable yet")
        return False, False

    def _fortify_backfill_ring(self, ct: Controller, center: Position) -> tuple[bool, bool]:
        """
        Fill neighbors around current conveyor tile with barriers while returning to core.
        Preserve conveyors and the ore/generator tile.
        Only target ROAD, MARKER, EMPTY, and ORE tiles.
        Natural walls or other structures are treated as already acceptable.
        """
        unresolved = False
        for target in self._ore_ring_positions(center):
            if not self._is_in_bounds(ct, target):
                continue
            if self.ore_target is not None and target == self.ore_target:
                continue

            marker_id = self._find_marker_at(ct, target)
            if marker_id is not None:
                unresolved = True
                if ct.can_destroy(target):
                    ct.destroy(target)
                    self._log(ct, f"backfill: destroyed marker at {target}")
                    return True, False
                self._log(ct, f"backfill: marker at {target} not destroyable")
                continue

            building_id = ct.get_tile_building_id(target)
            if building_id is not None:
                b_type = ct.get_entity_type(building_id)
                if b_type == EntityType.ROAD:
                    unresolved = True
                    if ct.can_destroy(target):
                        ct.destroy(target)
                        self._log(ct, f"backfill: destroyed road at {target}")
                        return True, False
                    self._log(ct, f"backfill: road at {target} not destroyable")
                    continue

                if b_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                    continue
                # Non-road structures (barriers/core/harvesters/etc.) are left as-is.
                continue

            env = ct.get_tile_env(target)
            if env in (
                Environment.EMPTY,
                Environment.ORE_TITANIUM,
                Environment.ORE_AXIONITE,
            ):
                unresolved = True
                if ct.get_action_cooldown() == 0 and ct.can_build_barrier(target):
                    ct.build_barrier(target)
                    self._log(ct, f"backfill: built barrier at {target}")
                    return True, False

                if ct.get_action_cooldown() != 0:
                    self._log(ct, f"backfill: waiting action cooldown for {target}")
                    return False, False

        if unresolved:
            return False, False
        return False, True

    @staticmethod
    def _ore_ring_positions(ore_pos: Position) -> list[Position]:
        return [
            Position(ore_pos.x + dx, ore_pos.y + dy)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if not (dx == 0 and dy == 0)
        ]

    @staticmethod
    def _is_in_bounds(ct: Controller, pos: Position) -> bool:
        return 0 <= pos.x < ct.get_map_width() and 0 <= pos.y < ct.get_map_height()

    def _swap_underfoot_to_core_conveyor(self, ct: Controller) -> tuple[bool, bool]:
        my_pos = ct.get_position()
        core_pos = self._adjacent_cardinal_core_tile(ct, my_pos)
        if core_pos is None:
            self._log(ct, "underfoot swap skipped: no adjacent friendly core tile")
            return False, True

        desired_dir = my_pos.direction_to(core_pos)
        if desired_dir not in CARDINAL_DIRECTIONS:
            self._log(ct, f"underfoot swap skipped: non-cardinal direction {desired_dir}")
            return False, True

        acted = False

        building_id = ct.get_tile_building_id(my_pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            b_team = ct.get_team(building_id)

            if b_type == EntityType.CONVEYOR and b_team == ct.get_team():
                try:
                    if ct.get_direction(building_id) == desired_dir:
                        self._log(
                            ct,
                            f"underfoot conveyor already correct at {my_pos} -> {desired_dir}",
                        )
                        return False, True
                except Exception:
                    pass

            if b_type != EntityType.CORE and b_team == ct.get_team() and ct.can_destroy(my_pos):
                ct.destroy(my_pos)
                acted = True
                self._log(ct, f"underfoot swap destroyed allied {b_type} at {my_pos}")

        marker_id = self._find_marker_at(ct, my_pos)
        if marker_id is not None and ct.can_destroy(my_pos):
            ct.destroy(my_pos)
            acted = True
            self._log(ct, f"underfoot swap destroyed marker at {my_pos}")

        if ct.get_action_cooldown() == 0 and ct.can_build_conveyor(my_pos, desired_dir):
            ct.build_conveyor(my_pos, desired_dir)
            self._log(ct, f"underfoot swap built conveyor at {my_pos} facing {desired_dir}")
            return True, True

        self._log(
            ct,
            (
                f"underfoot swap waiting: can_build={ct.can_build_conveyor(my_pos, desired_dir)}, "
                f"action_cd={ct.get_action_cooldown()}"
            ),
        )
        return acted, False

    def _adjacent_cardinal_core_tile(self, ct: Controller, pos: Position) -> Position | None:
        for d in CARDINAL_DIRECTIONS:
            check = pos.add(d)
            building_id = ct.get_tile_building_id(check)
            if building_id is None:
                continue
            if (
                ct.get_entity_type(building_id) == EntityType.CORE
                and ct.get_team(building_id) == ct.get_team()
            ):
                return check
        return None

    def _underfoot_conveyor_direction(self, ct: Controller, pos: Position) -> Direction | None:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return None
        b_type = ct.get_entity_type(building_id)
        if b_type not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            return None
        if ct.get_team(building_id) != ct.get_team():
            return None
        try:
            d = ct.get_direction(building_id)
        except Exception:
            return None
        if d in CARDINAL_DIRECTIONS:
            return d
        return None

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
        if not DEBUG_PRINTS:
            return
        if ct.get_current_round() >= 100:
            return
        print(
            f"[GC id={ct.get_id()} r={ct.get_current_round()}] {msg}",
            file=sys.stderr,
        )

    def _finish_turn(
        self,
        on_core_now: bool,
        acted: bool,
        failed: bool,
    ) -> tuple[bool, bool]:
        self.was_on_core_last_turn = on_core_now
        return acted, failed

    def should_suppress_main_movement(self, ct: Controller) -> bool:
        """
        While finalizing around ore, guarded mode should fully own movement.
        This prevents fallback navigation from moving the bot off the ore workflow.
        """
        _ = ct
        return self.ore_finalize_phase is not None
