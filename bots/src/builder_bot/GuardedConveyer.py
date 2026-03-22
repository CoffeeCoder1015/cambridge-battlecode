from cambc import Controller, Direction, EntityType, Environment, Position
import sys


class GuardedConveyer:
    """Greedy ore approach logic for guarded-conveyor mode."""

    ACTION_RADIUS_SQ = 2
    MOVE_DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
    ORE_ENVS = (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)
    DEBUG_PRINTS_ENABLED = True
    DEBUG_PRINTS_MAX_ROUND = 100

    def __init__(self) -> None:
        self._ore_target: Position | None = None
        self._generator_pos: Position | None = None
        self._starting_position: Position | None = None
        self._has_relocated = False
        self._has_returned_to_start = False

    def run(self, ct: Controller, known_symmetry, symmetry_analyzer) -> bool:
        """
        Returns True if this mode consumed the turn with a road build or move.
        """
        if self._generator_pos is None or self._starting_position is None:
            self._capture_adjacent_ore_setup(ct, symmetry_analyzer)

        if self._generator_pos is not None and self._starting_position is not None:
            self._dbg(
                ct,
                "guarded_setup active",
                f"generator={self._fmt_pos(self._generator_pos)} start={self._fmt_pos(self._starting_position)} relocated={self._has_relocated}",
            )
            return self._run_guarded_setup(ct)

        ore_positions = self._get_visible_ore_positions(ct, symmetry_analyzer)
        self._update_target(ct, ore_positions, known_symmetry)

        if self._ore_target is None:
            return False

        my_pos = ct.get_position()
        if self._dist_sq(my_pos, self._ore_target) <= self.ACTION_RADIUS_SQ:
            return False

        best_dir = self._get_greedy_step(ct, my_pos, self._ore_target)
        if best_dir is None:
            return False

        ahead = my_pos.add(best_dir)
        if not self._has_friendly_road(ct, ahead):
            if ct.can_build_road(ahead):
                ct.build_road(ahead)
                # Try to move after placing road on the same turn if legal.
                if ct.can_move(best_dir):
                    ct.move(best_dir)
                return True

        if ct.can_move(best_dir):
            ct.move(best_dir)
            return True

        return False

    def _capture_adjacent_ore_setup(self, ct: Controller, symmetry_analyzer) -> None:
        if self._generator_pos is not None and self._starting_position is not None:
            return

        my_pos = ct.get_position()
        ore_positions = self._get_visible_ore_positions(ct, symmetry_analyzer)
        adjacent_ores = [ore for ore in ore_positions if self._dist_sq(my_pos, ore) <= self.ACTION_RADIUS_SQ]
        if not adjacent_ores:
            return

        adjacent_ores.sort(key=lambda ore: (self._dist_sq(my_pos, ore), ore.x, ore.y))
        self._generator_pos = adjacent_ores[0]
        self._starting_position = my_pos
        self._has_relocated = False
        self._has_returned_to_start = False
        self._dbg(
            ct,
            "locked setup",
            f"generator={self._fmt_pos(self._generator_pos)} start={self._fmt_pos(self._starting_position)}",
        )

    def _run_guarded_setup(self, ct: Controller) -> bool:
        generator_pos = self._generator_pos
        starting_pos = self._starting_position
        if generator_pos is None or starting_pos is None:
            return False

        if not self._has_friendly_harvester(ct, generator_pos):
            if ct.can_build_harvester(generator_pos):
                self._dbg(ct, "building harvester", f"at={self._fmt_pos(generator_pos)}")
                ct.build_harvester(generator_pos)
                return True
            # Stay put and keep trying to build the generator first.
            self._dbg(
                ct,
                "waiting to build harvester",
                f"target={self._fmt_pos(generator_pos)} can_build=False",
            )
            return True

        if not self._has_relocated:
            relocate_dir = self._get_guard_relocation_dir(ct, generator_pos)
            if relocate_dir is not None:
                relocate_to = ct.get_position().add(relocate_dir)
                if not self._has_friendly_road(ct, relocate_to):
                    if ct.can_build_road(relocate_to):
                        self._dbg(ct, "building relocate road", f"at={self._fmt_pos(relocate_to)}")
                        ct.build_road(relocate_to)
                    else:
                        self._dbg(
                            ct,
                            "relocate road blocked",
                            f"target={self._fmt_pos(relocate_to)} can_build_road=False",
                        )

                if ct.can_move(relocate_dir):
                    self._dbg(
                        ct,
                        "relocating",
                        f"dir={relocate_dir} from={self._fmt_pos(ct.get_position())} to={self._fmt_pos(relocate_to)}",
                    )
                    ct.move(relocate_dir)
                    self._has_relocated = True
                    return True

                self._dbg(
                    ct,
                    "relocation move blocked",
                    f"dir={relocate_dir} target={self._fmt_pos(relocate_to)} can_move=False",
                )
                return True
            # Keep position while waiting for a valid relocation tile.
            self._dbg(
                ct,
                "relocation blocked",
                f"current={self._fmt_pos(ct.get_position())} generator={self._fmt_pos(generator_pos)}",
            )
            return True

        if not self._has_returned_to_start:
            wall_target = self._get_next_wall_target(
                ct,
                generator_pos,
                starting_pos,
                include_starting_pos=False,
            )
            if wall_target is not None:
                if self._prepare_tile_for_barrier(ct, wall_target):
                    return True
                if ct.can_build_barrier(wall_target):
                    self._dbg(ct, "building barrier", f"at={self._fmt_pos(wall_target)}")
                    ct.build_barrier(wall_target)
                    return True
                self._dbg(
                    ct,
                    "barrier blocked",
                    f"at={self._fmt_pos(wall_target)} can_build_barrier=False",
                )
                return True

            if self._same_pos(ct.get_position(), starting_pos):
                self._has_returned_to_start = True
                self._dbg(ct, "at starting_pos", f"start={self._fmt_pos(starting_pos)}")
                return True

            back_dir = self._get_greedy_step(ct, ct.get_position(), starting_pos)
            if back_dir is not None:
                back_to = ct.get_position().add(back_dir)
                if not self._has_friendly_road(ct, back_to):
                    if ct.can_build_road(back_to):
                        self._dbg(ct, "building return road", f"at={self._fmt_pos(back_to)}")
                        ct.build_road(back_to)
                    else:
                        self._dbg(
                            ct,
                            "return road blocked",
                            f"target={self._fmt_pos(back_to)} can_build_road=False",
                        )
                if ct.can_move(back_dir):
                    self._dbg(
                        ct,
                        "returning to start",
                        f"dir={back_dir} from={self._fmt_pos(ct.get_position())} to={self._fmt_pos(back_to)}",
                    )
                    ct.move(back_dir)
                    if self._same_pos(back_to, starting_pos):
                        self._has_returned_to_start = True
                    return True
                self._dbg(
                    ct,
                    "return move blocked",
                    f"dir={back_dir} target={self._fmt_pos(back_to)} can_move=False",
                )
                return True

            self._dbg(
                ct,
                "cannot path to start",
                f"current={self._fmt_pos(ct.get_position())} start={self._fmt_pos(starting_pos)}",
            )
            return True

        final_wall_target = self._get_next_wall_target(
            ct,
            generator_pos,
            starting_pos,
            include_starting_pos=True,
        )
        if final_wall_target is not None:
            if self._prepare_tile_for_barrier(ct, final_wall_target):
                return True
            if ct.can_build_barrier(final_wall_target):
                self._dbg(ct, "building final barrier", f"at={self._fmt_pos(final_wall_target)}")
                ct.build_barrier(final_wall_target)
                return True
            self._dbg(
                ct,
                "final barrier blocked",
                f"at={self._fmt_pos(final_wall_target)} can_build_barrier=False",
            )
            return True

        # Setup complete; do not fall back to roaming logic.
        self._dbg(
            ct,
            "no barrier action",
            f"current={self._fmt_pos(ct.get_position())} generator={self._fmt_pos(generator_pos)}",
        )
        return True

    def _get_visible_ore_positions(self, ct: Controller, symmetry_analyzer) -> list[Position]:
        ores: dict[tuple[int, int], Position] = {}

        # Leverage stored scan memory from symmetry analyzer and keep only visible ore.
        if symmetry_analyzer is not None and hasattr(symmetry_analyzer, "map_history"):
            for (x, y), env in symmetry_analyzer.map_history.items():
                if env in self.ORE_ENVS:
                    pos = Position(x, y)
                    if ct.is_in_vision(pos):
                        ores[(x, y)] = pos

        # Include freshly visible tiles this turn.
        for pos in ct.get_nearby_tiles():
            if ct.get_tile_env(pos) in self.ORE_ENVS:
                ores[(pos.x, pos.y)] = pos

        return list(ores.values())

    def _update_target(
        self,
        ct: Controller,
        ore_positions: list[Position],
        known_symmetry,
    ) -> None:
        if self._ore_target is not None:
            still_ore = any(
                p.x == self._ore_target.x and p.y == self._ore_target.y for p in ore_positions
            )
            if not still_ore:
                self._ore_target = None

        if self._ore_target is not None:
            return

        my_pos = ct.get_position()
        candidates = [
            ore for ore in ore_positions if self._dist_sq(my_pos, ore) > self.ACTION_RADIUS_SQ
        ]
        if not candidates:
            self._ore_target = None
            return

        # Use known_symmetry in tie-breaking to keep behaviour deterministic.
        if known_symmetry is None:
            self._ore_target = min(
                candidates,
                key=lambda ore: (self._dist_sq(my_pos, ore), ore.x, ore.y),
            )
        else:
            self._ore_target = min(
                candidates,
                key=lambda ore: (self._dist_sq(my_pos, ore), (ore.x + ore.y) % 2, ore.x, ore.y),
            )

    def _get_greedy_step(self, ct: Controller, cur: Position, target: Position) -> Direction | None:
        current_dist = self._dist_sq(cur, target)
        options: list[tuple[int, Direction]] = []

        for d in self.MOVE_DIRECTIONS:
            nxt = cur.add(d)
            if not (ct.is_tile_passable(nxt) or ct.can_build_road(nxt)):
                continue
            next_dist = self._dist_sq(nxt, target)
            if next_dist < current_dist:
                options.append((next_dist, d))

        if not options:
            return None

        options.sort(key=lambda item: item[0])
        return options[0][1]

    def _has_friendly_road(self, ct: Controller, pos: Position) -> bool:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        return (
            ct.get_entity_type(building_id) == EntityType.ROAD
            and ct.get_team(building_id) == ct.get_team()
        )

    def _has_friendly_harvester(self, ct: Controller, pos: Position) -> bool:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        return (
            ct.get_entity_type(building_id) == EntityType.HARVESTER
            and ct.get_team(building_id) == ct.get_team()
        )

    def _get_guard_relocation_dir(
        self,
        ct: Controller,
        generator_pos: Position,
    ) -> Direction | None:
        my_pos = ct.get_position()
        options: list[tuple[int, int, int, int, int, Direction]] = []

        for d in self.MOVE_DIRECTIONS:
            nxt = my_pos.add(d)

            if self._dist_sq(nxt, generator_pos) > self.ACTION_RADIUS_SQ:
                continue
            # Match existing road-then-move pattern used elsewhere:
            # a relocation tile is valid if we can stand there now OR can pave it first.
            if not (ct.is_tile_passable(nxt) or ct.can_build_road(nxt)):
                continue

            step_dx = abs(nxt.x - my_pos.x)
            step_dy = abs(nxt.y - my_pos.y)
            is_diagonal = 1 if step_dx == 1 and step_dy == 1 else 0
            is_core_adjacent = 1 if self._is_adjacent_to_friendly_core(ct, nxt) else 0
            options.append(
                (
                    -is_core_adjacent,  # Prefer core-adjacent, but do not require.
                    -is_diagonal,       # Then prefer diagonal.
                    self._dist_sq(nxt, generator_pos),
                    nxt.x,
                    nxt.y,
                    d,
                )
            )

        if not options:
            return None

        options.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
        return options[0][5]

    def _is_adjacent_to_friendly_core(self, ct: Controller, pos: Position) -> bool:
        for d in [Direction.CENTRE] + self.MOVE_DIRECTIONS:
            check_pos = pos.add(d)
            if not ct.is_in_vision(check_pos):
                continue
            building_id = ct.get_tile_building_id(check_pos)
            if building_id is None:
                continue
            if (
                ct.get_entity_type(building_id) == EntityType.CORE
                and ct.get_team(building_id) == ct.get_team()
            ):
                return True
        return False

    def _get_next_wall_target(
        self,
        ct: Controller,
        generator_pos: Position,
        starting_pos: Position,
        include_starting_pos: bool,
    ) -> Position | None:
        neighbors: list[Position] = []
        for d in self.MOVE_DIRECTIONS:
            p = generator_pos.add(d)
            if not ct.is_in_vision(p):
                continue
            if (not include_starting_pos) and p.x == starting_pos.x and p.y == starting_pos.y:
                continue
            if self._dist_sq(ct.get_position(), p) > self.ACTION_RADIUS_SQ:
                continue
            # Never overwrite generator tile or core.
            building_id = ct.get_tile_building_id(p)
            if building_id is not None:
                etype = ct.get_entity_type(building_id)
                if etype in (EntityType.HARVESTER, EntityType.CORE):
                    continue
            neighbors.append(p)

        neighbors.sort(key=lambda p: (self._dist_sq(ct.get_position(), p), p.x, p.y))
        for p in neighbors:
            if ct.can_build_barrier(p) or self._is_friendly_clearable_blocker(ct, p):
                return p
        return None

    def _is_friendly_clearable_blocker(self, ct: Controller, pos: Position) -> bool:
        if self._has_friendly_marker_at_pos(ct, pos):
            return ct.can_destroy(pos)

        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        if ct.get_team(building_id) != ct.get_team():
            return False
        if ct.get_entity_type(building_id) != EntityType.ROAD:
            return False
        return ct.can_destroy(pos)

    def _prepare_tile_for_barrier(self, ct: Controller, pos: Position) -> bool:
        """
        Try to clear friendly blockers that prevent barrier placement.
        Returns True if we consumed the turn.
        """
        if ct.can_build_barrier(pos):
            return False

        if self._has_friendly_marker_at_pos(ct, pos):
            if ct.can_destroy(pos):
                self._dbg(ct, "destroying blocker", f"at={self._fmt_pos(pos)} type={EntityType.MARKER}")
                ct.destroy(pos)
                return True
            self._dbg(
                ct,
                "cannot destroy blocker",
                f"at={self._fmt_pos(pos)} type={EntityType.MARKER}",
            )
            return False

        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False

        if ct.get_team(building_id) != ct.get_team():
            return False

        blocker_type = ct.get_entity_type(building_id)
        if blocker_type not in (EntityType.ROAD, EntityType.MARKER):
            return False

        if ct.can_destroy(pos):
            self._dbg(
                ct,
                "destroying blocker",
                f"at={self._fmt_pos(pos)} type={blocker_type}",
            )
            ct.destroy(pos)
            return True

        self._dbg(
            ct,
            "cannot destroy blocker",
            f"at={self._fmt_pos(pos)} type={blocker_type}",
        )
        return False

    def _has_friendly_marker_at_pos(self, ct: Controller, pos: Position) -> bool:
        for entity_id in ct.get_nearby_entities():
            if ct.get_entity_type(entity_id) != EntityType.MARKER:
                continue
            if ct.get_team(entity_id) != ct.get_team():
                continue
            marker_pos = ct.get_position(entity_id)
            if marker_pos.x == pos.x and marker_pos.y == pos.y:
                return True
        return False

    @staticmethod
    def _same_pos(a: Position, b: Position) -> bool:
        return a.x == b.x and a.y == b.y

    def _dbg(self, ct: Controller, stage: str, extra: str) -> None:
        if not self.DEBUG_PRINTS_ENABLED:
            return
        if ct.get_current_round() > self.DEBUG_PRINTS_MAX_ROUND:
            return
        print(
            f"[GuardedConveyer][turn={ct.get_current_round()}][r={ct.get_current_round()}][id={ct.get_id()}] {stage}: {extra}",
            file=sys.stderr,
        )

    @staticmethod
    def _fmt_pos(pos: Position | None) -> str:
        if pos is None:
            return "None"
        return f"({pos.x},{pos.y})"

    @staticmethod
    def _dist_sq(a: Position, b: Position) -> int:
        return (a.x - b.x) ** 2 + (a.y - b.y) ** 2
