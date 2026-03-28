import sys

from cambc import Controller, Direction, EntityType, Environment, Position

from ..Offense.BreakBridges import BreakBridges


class Hound:
    def __init__(self, debug_prints: bool = False):
        self.debug_prints = debug_prints
        self.break_bridges = BreakBridges(debug_prints=debug_prints)
        self._tracked_bridge_tile: tuple[int, int] | None = None

    def _log(self, ct: Controller, message: str) -> None:
        if not self.debug_prints:
            return
        print(
            f"[Hound][R{ct.get_current_round()}][id={ct.get_id()}] {message}",
            file=sys.stderr,
        )

    def _try_attack_underfoot_enemy_bridge(self, ct: Controller) -> bool:
        my_pos = ct.get_position()
        building_id = ct.get_tile_building_id(my_pos)
        if building_id is None:
            return False

        try:
            building_type = ct.get_entity_type(building_id)
            building_team = ct.get_team(building_id)
        except Exception:
            return False

        if building_type != EntityType.BRIDGE or building_team == ct.get_team():
            return False

        if ct.can_fire(my_pos):
            ct.fire(my_pos)
            self._log(
                ct,
                f"on enemy bridge and fired underfoot at ({my_pos.x},{my_pos.y})",
            )
        else:
            self._log(
                ct,
                f"on enemy bridge but cannot fire underfoot this turn at ({my_pos.x},{my_pos.y})",
            )
        return True

    def _enemy_core_facing_direction(
        self,
        ct: Controller,
        enemy_core_target: tuple[int, int] | None,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
        origin_pos: Position | None = None,
    ) -> tuple[Direction, tuple[int, int] | None]:
        resolved_target = enemy_core_target
        if resolved_target is None:
            resolved_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)

        if resolved_target is None:
            return Direction.NORTH, None

        my_pos = origin_pos if origin_pos is not None else ct.get_position()
        core_pos_obj = Position(resolved_target[0], resolved_target[1])
        facing = my_pos.direction_to(core_pos_obj)
        if facing == Direction.CENTRE:
            facing = Direction.NORTH
        return facing, resolved_target

    @staticmethod
    def _ordered_directions(base: Direction) -> tuple[Direction, ...]:
        if base == Direction.CENTRE:
            base = Direction.NORTH

        dirs: list[Direction] = [base]
        right = base
        left = base
        for _ in range(3):
            right = right.rotate_right()
            left = left.rotate_left()
            dirs.append(right)
            dirs.append(left)
        dirs.append(base.opposite())

        ordered: list[Direction] = []
        seen: set[Direction] = set()
        for d in dirs:
            if d == Direction.CENTRE or d in seen:
                continue
            seen.add(d)
            ordered.append(d)
        return tuple(ordered)

    def _try_build_sentinel_on_tile(
        self,
        ct: Controller,
        sentinel_tile: Position,
        enemy_core_target: tuple[int, int] | None,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
    ) -> tuple[bool, tuple[int, int] | None]:
        try:
            building_id = ct.get_tile_building_id(sentinel_tile)
        except Exception:
            return False, enemy_core_target
        if building_id is not None:
            try:
                b_type = ct.get_entity_type(building_id)
                b_team = ct.get_team(building_id)
            except Exception:
                b_type = None
                b_team = None
            if b_type == EntityType.SENTINEL and b_team == ct.get_team():
                self._tracked_bridge_tile = None
                return True, enemy_core_target
            return False, enemy_core_target

        try:
            env = ct.get_tile_env(sentinel_tile)
        except Exception:
            return False, enemy_core_target
        if env != Environment.EMPTY:
            return False, enemy_core_target

        facing, resolved_target = self._enemy_core_facing_direction(
            ct=ct,
            enemy_core_target=enemy_core_target,
            core_pos=core_pos,
            known_symmetry=known_symmetry,
            origin_pos=sentinel_tile,
        )
        enemy_core_target = resolved_target

        if ct.can_build_sentinel(sentinel_tile, facing):
            ct.build_sentinel(sentinel_tile, facing)
            self._log(
                ct,
                (
                    f"built sentinel at ({sentinel_tile.x},{sentinel_tile.y}) "
                    f"facing={facing} enemy_core_target={enemy_core_target}"
                ),
            )
            self._tracked_bridge_tile = None
        else:
            self._log(
                ct,
                (
                    "cleared tile ready but cannot build sentinel "
                    f"at ({sentinel_tile.x},{sentinel_tile.y}) facing={facing}; "
                    f"action_cd={ct.get_action_cooldown()}"
                ),
            )
        return True, enemy_core_target

    def _try_move_off_and_build_sentinel_same_turn(
        self,
        ct: Controller,
        enemy_core_target: tuple[int, int] | None,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
    ) -> tuple[bool, tuple[int, int] | None]:
        sentinel_tile = ct.get_position()
        building_id = ct.get_tile_building_id(sentinel_tile)
        if building_id is not None:
            return False, enemy_core_target

        try:
            env = ct.get_tile_env(sentinel_tile)
        except Exception:
            return False, enemy_core_target
        if env != Environment.EMPTY:
            return False, enemy_core_target

        if ct.get_move_cooldown() != 0 or ct.get_action_cooldown() != 0:
            self._log(
                ct,
                (
                    "cleared bridge tile underfoot but waiting for cds "
                    f"(move_cd={ct.get_move_cooldown()}, action_cd={ct.get_action_cooldown()})"
                ),
            )
            return True, enemy_core_target

        facing, resolved_target = self._enemy_core_facing_direction(
            ct=ct,
            enemy_core_target=enemy_core_target,
            core_pos=core_pos,
            known_symmetry=known_symmetry,
            origin_pos=sentinel_tile,
        )
        enemy_core_target = resolved_target

        move_dir = None
        for cand in self._ordered_directions(facing.opposite()):
            if ct.can_move(cand):
                move_dir = cand
                break

        if move_dir is None:
            self._log(
                ct,
                (
                    "cleared bridge tile underfoot but cannot vacate tile this turn; "
                    "waiting to place sentinel"
                ),
            )
            return True, enemy_core_target

        ct.move(move_dir)
        post_pos = ct.get_position()
        self._log(
            ct,
            (
                f"vacated cleared bridge tile ({sentinel_tile.x},{sentinel_tile.y}) "
                f"via {move_dir} to ({post_pos.x},{post_pos.y}); attempting sentinel build now"
            ),
        )

        built_or_waiting, enemy_core_target = self._try_build_sentinel_on_tile(
            ct=ct,
            sentinel_tile=sentinel_tile,
            enemy_core_target=enemy_core_target,
            core_pos=core_pos,
            known_symmetry=known_symmetry,
        )
        if built_or_waiting:
            return True, enemy_core_target

        self._log(
            ct,
            (
                "sentinel placement could not proceed after vacating; "
                "clearing tracked bridge state"
            ),
        )
        self._tracked_bridge_tile = None
        return True, enemy_core_target

    def _continue_tracked_bridge_work(
        self,
        ct: Controller,
        enemy_core_target: tuple[int, int] | None,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
    ) -> tuple[bool, tuple[int, int] | None]:
        if self._tracked_bridge_tile is None:
            return False, enemy_core_target

        my_pos = ct.get_position()
        if (my_pos.x, my_pos.y) != self._tracked_bridge_tile:
            tracked_tile = Position(
                self._tracked_bridge_tile[0], self._tracked_bridge_tile[1]
            )
            built_or_waiting, enemy_core_target = self._try_build_sentinel_on_tile(
                ct=ct,
                sentinel_tile=tracked_tile,
                enemy_core_target=enemy_core_target,
                core_pos=core_pos,
                known_symmetry=known_symmetry,
            )
            if built_or_waiting:
                return True, enemy_core_target
            self._log(
                ct,
                (
                    f"left tracked bridge tile {self._tracked_bridge_tile}; "
                    "clearing tracked state"
                ),
            )
            self._tracked_bridge_tile = None
            return False, enemy_core_target

        if self._try_attack_underfoot_enemy_bridge(ct):
            return True, enemy_core_target

        built_or_waiting, enemy_core_target = self._try_move_off_and_build_sentinel_same_turn(
            ct=ct,
            enemy_core_target=enemy_core_target,
            core_pos=core_pos,
            known_symmetry=known_symmetry,
        )
        if built_or_waiting:
            return True, enemy_core_target

        self._log(
            ct,
            "tracked bridge tile no longer attackable/empty; clearing tracked state",
        )
        self._tracked_bridge_tile = None
        return False, enemy_core_target

    def compute_enemy_core_target(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
    ) -> tuple[int, int] | None:
        if core_pos is None or known_symmetry is None:
            return None

        core_x, core_y = core_pos
        max_x = ct.get_map_width() - 1
        max_y = ct.get_map_height() - 1

        if known_symmetry == 101:  # REF_X
            return (max_x - core_x, core_y)
        if known_symmetry == 102:  # REF_Y
            return (core_x, max_y - core_y)
        if known_symmetry == 103:  # ROT
            return (max_x - core_x, max_y - core_y)
        return None

    def try_enter_mode(
        self,
        ct: Controller,
        agentmode: str | None,
        known_symmetry: int | None,
        core_pos: tuple[int, int] | None,
        set_nav_target,
    ) -> tuple[str | None, tuple[int, int] | None]:
        # Enforce one-way transition: only allow None -> HOUND.
        # This guarantees HOUND never overrides GUARDED_CONVEYER.
        if agentmode is not None or known_symmetry is None:
            return agentmode, None

        hound_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)
        if hound_target is None:
            return agentmode, None

        next_mode = "HOUND"
        set_nav_target(*hound_target)

        if self.debug_prints:
            print(
                (
                    f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                    f"entering HOUND mode -> target enemy core at {hound_target} "
                    f"(symmetry={known_symmetry}, core={core_pos})"
                ),
                file=sys.stderr,
            )

        return next_mode, hound_target

    def run(
        self,
        ct: Controller,
        enemy_core_target: tuple[int, int] | None,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
        set_nav_target,
        execute_nav_step,
    ) -> tuple[bool, tuple[int, int] | None]:
        tracked_acted, enemy_core_target = self._continue_tracked_bridge_work(
            ct=ct,
            enemy_core_target=enemy_core_target,
            core_pos=core_pos,
            known_symmetry=known_symmetry,
        )
        if tracked_acted:
            return True, enemy_core_target

        if self.break_bridges.is_enemy_core_visible(ct):
            bridge_target, total_enemy_bridges, occupied_enemy_bridges = (
                self.break_bridges.select_bridge_target_with_stats(ct)
            )
            self._log(
                ct,
                (
                    "enemy core visible; "
                    f"enemy_bridges_seen={total_enemy_bridges} "
                    f"occupied_enemy_bridges={occupied_enemy_bridges}"
                ),
            )
            if bridge_target is not None:
                my_pos = ct.get_position()
                if my_pos.x == bridge_target.x and my_pos.y == bridge_target.y:
                    if self._try_attack_underfoot_enemy_bridge(ct):
                        self._tracked_bridge_tile = (my_pos.x, my_pos.y)
                        return True, enemy_core_target
                    self._log(ct, "underfoot tile no longer enemy bridge (likely empty/destroyed)")
                    built_or_waiting, enemy_core_target = self._try_move_off_and_build_sentinel_same_turn(
                        ct=ct,
                        enemy_core_target=enemy_core_target,
                        core_pos=core_pos,
                        known_symmetry=known_symmetry,
                    )
                    if built_or_waiting:
                        return True, enemy_core_target
                    return True, enemy_core_target

                self._log(
                    ct,
                    (
                        f"bridge target selected=({bridge_target.x},{bridge_target.y}) "
                        f"from=({my_pos.x},{my_pos.y})"
                    ),
                )
                set_nav_target(bridge_target.x, bridge_target.y)
                moved = execute_nav_step(ct)
                post_pos = ct.get_position()
                if (
                    post_pos.x == bridge_target.x
                    and post_pos.y == bridge_target.y
                    and self._try_attack_underfoot_enemy_bridge(ct)
                ):
                    self._tracked_bridge_tile = (post_pos.x, post_pos.y)
                    return True, enemy_core_target
                self._log(
                    ct,
                    (
                        f"bridge move result moved={moved} "
                        f"post=({post_pos.x},{post_pos.y}) "
                        f"target=({bridge_target.x},{bridge_target.y})"
                    ),
                )
                # Keep the hound committed to this action even if movement is blocked this turn.
                return True, enemy_core_target
            self._log(ct, "enemy core visible but no open enemy bridge target found")

        if enemy_core_target is None:
            hound_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)
            if hound_target is None:
                return False, enemy_core_target
            enemy_core_target = hound_target

        set_nav_target(*enemy_core_target)
        return execute_nav_step(ct), enemy_core_target
