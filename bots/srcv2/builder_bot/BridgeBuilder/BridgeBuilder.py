import random
import sys
from typing import Any, Literal

from cambc import Controller, Direction, EntityType, Environment, Position

from ..Movement.TangentNav import TangentNav
from ..helper import get_cost_affordability

POST_HARVESTER_GREEDY_RETURN_CHANCE_PERCENT = 0

ACTION_RADIUS_SQ = 2
ORE_ENVS = (Environment.ORE_TITANIUM,)
_PASSABLE_BUILDINGS = (
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
)
_CARDINAL_DIRECTIONS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)
_ADJACENT_DELTAS = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
)
_ORE_TARGET_BLACKLIST_ROUNDS = 80

Phase = Literal["SEEK_ORE", "RETURN_CORE"]


class BridgeBuilder:
    # Master toggle for high-detail BridgeBuilder navigation logs.
    _NAV_DEBUG = True
    # Feature flag: when enabled, only the target unit id emits logs.
    _NAV_DEBUG_ONLY_TARGET_ID = True
    _NAV_DEBUG_TARGET_UNIT_ID = 3
    _NAV_DEBUG_START_ROUND = 300
    _NAV_DEBUG_END_ROUND = 420

    def __init__(self) -> None:
        self.ore_target: tuple[int, int] | None = None
        self.agent_phase: Phase = "SEEK_ORE"
        self._post_build_align_ore_target: tuple[int, int] | None = None
        self._ore_nav = TangentNav()
        self._ore_nav_target: tuple[int, int] | None = None
        self._return_nav = TangentNav()
        self._return_nav_target: tuple[int, int] | None = None
        self._post_bridge_target: tuple[int, int] | None = None
        self._diag_align_nav = TangentNav()
        self._diag_align_nav_target: tuple[int, int] | None = None
        self._diag_align_ore_target: tuple[int, int] | None = None
        self._ore_blacklist: dict[tuple[int, int], int] = {}
        self._greedy_return_no_join_merge = False
        self._launcher_pending_anchor: tuple[int, int] | None = None

    def run(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
        symmetry_analyzer: Any | None,
    ) -> bool:
        my_pos = ct.get_position()
        self._nav_dbg(
            ct,
            (
                f"Tick phase={self.agent_phase} pos=({my_pos.x},{my_pos.y}) "
                f"ore_target={self.ore_target} ore_nav_target={self._ore_nav_target} "
                f"return_nav_target={self._return_nav_target} "
                f"post_bridge_target={self._post_bridge_target} "
                f"diag_align_target={self._diag_align_nav_target} "
                f"ore_blacklist={len(self._ore_blacklist)}"
            ),
        )
        map_history = getattr(symmetry_analyzer, "map_history", None)
        if isinstance(map_history, dict):
            self._ore_nav.attach_terrain_memory(map_history)
            self._return_nav.attach_terrain_memory(map_history)
            self._diag_align_nav.attach_terrain_memory(map_history)
        self._cleanup_ore_blacklist(ct)
        if self._handle_pending_launcher_after_bridge(ct):
            return True

        if self.agent_phase == "RETURN_CORE":
            return self._run_return_core(ct, core_pos)

        if self._post_build_align_ore_target is not None:
            return self._run_post_build_cardinal_alignment(ct)

        visible_ores = self._visible_ores_from_scan(ct, symmetry_analyzer)
        self._nav_dbg(
            ct,
            f"Visible ore count={len(visible_ores)} core_pos={core_pos}",
        )

        if self.ore_target is not None:
            if self._is_ore_blacklisted(ct, self.ore_target):
                self._nav_dbg(ct, f"Clearing blacklisted ore target {self.ore_target}.")
                self._clear_ore_target()
            else:
                ore_pos = Position(self.ore_target[0], self.ore_target[1])

                # Only evaluate conditions if the target is ACTUALLY in vision
                if ct.is_in_vision(ore_pos):
                    completed_extractor = self._ore_has_completed_extractor(ct, ore_pos)
                    blocked_type = self._ore_blocking_structure_type(ct, ore_pos)

                    if completed_extractor or blocked_type is not None:
                        self._nav_dbg(
                            ct,
                            (
                                "Clearing ore target "
                                f"{self.ore_target}: "
                                f"completed_extractor={completed_extractor} "
                                f"blocked_type={blocked_type}"
                            ),
                        )
                        self._clear_ore_target()

        if self.ore_target is None:
            self.ore_target = self._select_reachable_ore(ct, my_pos, visible_ores, map_history)
            self._nav_dbg(ct, f"Selected ore target -> {self.ore_target}")

        if self.ore_target is None:
            self._nav_dbg(ct, "No ore target; falling back to center exploration nav.")
            return self._run_center_exploration(ct)

        ore_pos = Position(self.ore_target[0], self.ore_target[1])
        if self._should_run_diagonal_ore_alignment(my_pos, ore_pos):
            if self._run_diagonal_ore_alignment(ct, ore_pos):
                return True
        else:
            self._clear_diagonal_alignment_state()

        if self._in_action_radius(my_pos, ore_pos):
            if self._handle_enemy_road_on_ore(ct, ore_pos):
                return True

            # Avoid diagonal extractor placement attempts; bridge/conveyor follow-up
            # requires clean NEWS adjacency around the extractor tile.
            if not self._is_adjacent_cardinal(my_pos, ore_pos):
                self._move_to_cardinal_adjacent_tile(ct, ore_pos)
                return True

            build_result = self._build_generator_on_ore(ct, ore_pos)
            if build_result == "built":
                self._roll_post_harvester_return_mode(ct)
                self._clear_ore_target()
                self._start_post_build_alignment(ore_pos)
                self._return_nav_target = None
                self._post_bridge_target = None
                return True
            if build_result == "waiting_money":
                # Hold position and save for extractor.
                return True
            if build_result == "blocked":
                self._clear_ore_target()
                return True
            return True

        move_dir = self._next_nav_move(
            ct,
            nav=self._ore_nav,
            nav_target_attr="_ore_nav_target",
            target=(ore_pos.x, ore_pos.y),
        )
        if move_dir is None:
            self._nav_dbg(
                ct,
                (
                    f"Ore navigation returned None for target=({ore_pos.x},{ore_pos.y}); "
                    "clearing ore target."
                ),
            )
            self._clear_ore_target()
            return True
        self._nav_dbg(
            ct,
            f"Ore navigation move_dir={move_dir.name} target=({ore_pos.x},{ore_pos.y})",
        )
        return self._road_then_move(ct, move_dir)

    def _run_return_core(self, ct: Controller, core_pos: tuple[int, int] | None) -> bool:
        if core_pos is None:
            self._nav_dbg(ct, "Return-core phase with unknown core_pos; holding.")
            return True

        my_pos = ct.get_position()
        if self._is_on_friendly_core(ct, my_pos):
            self._nav_dbg(ct, "Reached friendly core tile; finishing return cycle.")
            self._finish_return_cycle()
            return True

        # Match old bridge cycle: after placing a bridge, move to that endpoint before
        # selecting another bridge segment.
        if self._post_bridge_target is not None:
            tx, ty = self._post_bridge_target
            if (my_pos.x, my_pos.y) == (tx, ty):
                self._nav_dbg(
                    ct,
                    f"Arrived at post-bridge target=({tx},{ty}); clearing target.",
                )
                self._post_bridge_target = None
                self._return_nav_target = None
            else:
                move_dir = self._next_nav_move(
                    ct,
                    nav=self._return_nav,
                    nav_target_attr="_return_nav_target",
                    target=(tx, ty),
                )
                if move_dir is None:
                    self._nav_dbg(
                        ct,
                        f"No nav move toward post-bridge target=({tx},{ty}); holding.",
                    )
                    return True
                self._nav_dbg(
                    ct,
                    f"Post-bridge navigation move_dir={move_dir.name} target=({tx},{ty})",
                )
                self._road_then_move(ct, move_dir)
                new_pos = ct.get_position()
                if (new_pos.x, new_pos.y) == (tx, ty):
                    self._post_bridge_target = None
                    self._return_nav_target = None
                return True

        skip_bridge_placement = False
        if self._greedy_return_no_join_merge:
            self._nav_dbg(
                ct,
                "Greedy return active; skipping adjacent endpoint join shortcut.",
            )
        else:
            endpoint_result = self._try_build_adjacent_endpoint_conveyor(ct, my_pos)
            if endpoint_result == "completed_cycle":
                self._nav_dbg(
                    ct,
                    "Adjacent endpoint conveyor placed; finishing return cycle for this ore.",
                )
                self._finish_return_cycle()
                return True
            skip_bridge_placement = endpoint_result == "continue_nav"
            if endpoint_result == "handled":
                return True

        move_target = core_pos
        if not skip_bridge_placement:
            bridge_target = self._select_bridge_target_toward_core(
                ct=ct,
                start_pos=my_pos,
                core_pos=core_pos,
                allow_chain_join=not self._greedy_return_no_join_merge,
                allow_merge_with_existing_return_path=(
                    not self._greedy_return_no_join_merge
                ),
            )
            if bridge_target is None:
                self._nav_dbg(
                    ct,
                    f"No bridge target; navigating directly to core={move_target}.",
                )
            else:
                if self._is_on_friendly_bridge(ct, my_pos):
                    # Already standing on a friendly bridge tile: skip bridge placement and
                    # continue along normal return navigation.
                    self._nav_dbg(
                        ct,
                        (
                            f"Standing on friendly bridge at ({my_pos.x},{my_pos.y}); "
                            f"skipping bridge build and navigating to core={move_target}."
                        ),
                    )
                else:
                    # Match old bridge-cycle behavior: wait until bridge placement is possible.
                    if ct.get_action_cooldown() != 0:
                        return True

                    affordable_bridge, _, _ = get_cost_affordability(ct, "get_bridge_cost")
                    if not affordable_bridge:
                        # Hold position and save for bridge to maintain chain behavior.
                        self._nav_dbg(ct, "Bridge not affordable; holding instead of moving.")
                        return True

                    if self._try_attack_underfoot_enemy_road(ct, my_pos):
                        return True

                    target_is_existing_return_path = self._is_on_friendly_return_path(
                        ct, bridge_target
                    )
                    if (
                        self._greedy_return_no_join_merge
                        and target_is_existing_return_path
                    ):
                        self._nav_dbg(
                            ct,
                            (
                                "Greedy return rejected bridge merge target at "
                                f"({bridge_target.x},{bridge_target.y}); holding."
                            ),
                        )
                        return True
                    self._clear_underfoot_for_bridge(ct, my_pos)

                    if ct.can_build_bridge(my_pos, bridge_target):
                        ct.build_bridge(my_pos, bridge_target)
                        self._launcher_pending_anchor = (my_pos.x, my_pos.y)
                        if self._is_on_friendly_core(
                            ct, bridge_target
                        ) or (
                            target_is_existing_return_path
                            and not self._greedy_return_no_join_merge
                        ):
                            self._finish_return_cycle()
                            return True
                        self._post_bridge_target = (bridge_target.x, bridge_target.y)
                        move_target = self._post_bridge_target
                        self._nav_dbg(
                            ct,
                            (
                                f"Built bridge toward ({bridge_target.x},{bridge_target.y}); "
                                f"post_bridge_target={self._post_bridge_target}"
                            ),
                        )
                    else:
                        # Roads/conveyors underfoot can block start tile bridge placement.
                        if self._clear_underfoot_for_bridge(ct, my_pos) and ct.can_build_bridge(
                            my_pos, bridge_target
                        ):
                            ct.build_bridge(my_pos, bridge_target)
                            self._launcher_pending_anchor = (my_pos.x, my_pos.y)
                            if self._is_on_friendly_core(
                                ct, bridge_target
                            ) or (
                                target_is_existing_return_path
                                and not self._greedy_return_no_join_merge
                            ):
                                self._finish_return_cycle()
                                return True
                            self._post_bridge_target = (bridge_target.x, bridge_target.y)
                            move_target = self._post_bridge_target
                            self._nav_dbg(
                                ct,
                                (
                                    "Built bridge after underfoot clear; "
                                    f"post_bridge_target={self._post_bridge_target}"
                                ),
                            )
                        else:
                            self._nav_dbg(
                                ct,
                                (
                                    f"Cannot build bridge from ({my_pos.x},{my_pos.y}) "
                                    f"to ({bridge_target.x},{bridge_target.y}); holding."
                                ),
                            )
                            return True
        else:
            self._nav_dbg(
                ct,
                "Adjacent endpoint shortcut complete; skipping bridge build and resuming nav.",
            )

        move_dir = self._next_nav_move(
            ct,
            nav=self._return_nav,
            nav_target_attr="_return_nav_target",
            target=move_target,
        )
        if move_dir is None:
            self._nav_dbg(
                ct,
                f"Return navigation returned None for move_target={move_target}; holding.",
            )
            return True
        self._nav_dbg(
            ct,
            f"Return navigation move_dir={move_dir.name} move_target={move_target}",
        )
        return self._road_then_move(ct, move_dir)

    def _try_build_adjacent_endpoint_conveyor(
        self,
        ct: Controller,
        my_pos: Position,
    ) -> Literal["none", "handled", "continue_nav", "completed_cycle"]:
        endpoint_types = (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
        )
        scan_log_parts: list[str] = []
        candidates: list[tuple[Direction, Position, EntityType]] = []

        for desired_dir in _CARDINAL_DIRECTIONS:
            endpoint_pos = my_pos.add(desired_dir)
            if not (
                0 <= endpoint_pos.x < ct.get_map_width()
                and 0 <= endpoint_pos.y < ct.get_map_height()
            ):
                scan_log_parts.append(f"{desired_dir.name}:OOB")
                continue

            endpoint_building_id = ct.get_tile_building_id(endpoint_pos)
            if endpoint_building_id is None:
                scan_log_parts.append(
                    f"{desired_dir.name}:EMPTY@({endpoint_pos.x},{endpoint_pos.y})"
                )
                continue

            endpoint_type = ct.get_entity_type(endpoint_building_id)
            endpoint_team = ct.get_team(endpoint_building_id)
            try:
                endpoint_dir = ct.get_direction(endpoint_building_id)
                endpoint_dir_name = endpoint_dir.name
            except Exception:
                endpoint_dir_name = "NA"
            is_friendly_endpoint = (
                endpoint_team == ct.get_team() and endpoint_type in endpoint_types
            )
            scan_log_parts.append(
                (
                    f"{desired_dir.name}:{endpoint_type.name}:"
                    f"{'ALLY' if endpoint_team == ct.get_team() else 'ENEMY'}:"
                    f"dir={endpoint_dir_name}:"
                    f"cand={'Y' if is_friendly_endpoint else 'N'}"
                )
            )
            if is_friendly_endpoint:
                candidates.append((desired_dir, endpoint_pos, endpoint_type))

        self._nav_dbg(
            ct,
            (
                "Adjacent endpoint scan "
                f"from=({my_pos.x},{my_pos.y}) "
                f"results=[{', '.join(scan_log_parts)}]"
            ),
        )

        if not candidates:
            return "none"

        desired_dir, endpoint_pos, endpoint_type = candidates[0]
        self._nav_dbg(
            ct,
            (
                "Adjacent endpoint shortcut selected "
                f"dir={desired_dir.name} endpoint=({endpoint_pos.x},{endpoint_pos.y}) "
                f"type={endpoint_type.name}"
            ),
        )

        my_building_id = ct.get_tile_building_id(my_pos)
        if my_building_id is not None and ct.get_team(my_building_id) == ct.get_team():
            my_building_type = ct.get_entity_type(my_building_id)
            if my_building_type in (
                EntityType.CONVEYOR,
                EntityType.ARMOURED_CONVEYOR,
            ):
                try:
                    if ct.get_direction(my_building_id) == desired_dir:
                        self._nav_dbg(
                            ct,
                            (
                                "Adjacent endpoint conveyor shortcut already satisfied "
                                f"at ({my_pos.x},{my_pos.y}) facing {desired_dir.name}; "
                                "continuing normal return behavior."
                            ),
                        )
                        return "continue_nav"
                except Exception:
                    pass

        affordable_conveyor, _, _ = get_cost_affordability(ct, "get_conveyor_cost")
        if not affordable_conveyor:
            self._nav_dbg(
                ct,
                (
                    "Adjacent endpoint conveyor shortcut waiting for resources "
                    f"facing {desired_dir.name}."
                ),
            )
            return "handled"

        if ct.get_action_cooldown() != 0:
            self._nav_dbg(
                ct,
                (
                    "Adjacent endpoint conveyor shortcut waiting for action cooldown "
                    f"action_cd={ct.get_action_cooldown()} facing {desired_dir.name}."
                ),
            )
            return "handled"

        if ct.can_build_conveyor(my_pos, desired_dir):
            ct.build_conveyor(my_pos, desired_dir)
            self._nav_dbg(
                ct,
                (
                    "Built adjacent endpoint conveyor shortcut "
                    f"at ({my_pos.x},{my_pos.y}) facing {desired_dir.name} "
                    f"toward ({endpoint_pos.x},{endpoint_pos.y}) type={endpoint_type.name}."
                ),
            )
            return "completed_cycle"

        acted = False
        my_building_id = ct.get_tile_building_id(my_pos)
        if my_building_id is not None:
            my_building_type = ct.get_entity_type(my_building_id)
            if my_building_type != EntityType.CORE and ct.can_destroy(my_pos):
                ct.destroy(my_pos)
                acted = True

        if BridgeBuilder._has_friendly_marker_at(ct, my_pos) and ct.can_destroy(my_pos):
            ct.destroy(my_pos)
            acted = True

        if acted:
            self._nav_dbg(
                ct,
                (
                    "Cleared underfoot blocker for adjacent endpoint conveyor shortcut "
                    f"at ({my_pos.x},{my_pos.y}); retrying next turn."
                ),
            )
            return "handled"

        self._nav_dbg(
            ct,
            (
                "Adjacent endpoint exists but cannot build conveyor this turn "
                f"at ({my_pos.x},{my_pos.y}) facing {desired_dir.name}; "
                "holding to preserve shortcut priority."
            ),
        )
        return "handled"

    def _run_center_exploration(self, ct: Controller) -> bool:
        target = (ct.get_map_width() // 2, ct.get_map_height() // 2)
        move_dir = self._next_nav_move(
            ct,
            nav=self._ore_nav,
            nav_target_attr="_ore_nav_target",
            target=target,
        )
        if move_dir is None:
            self._nav_dbg(
                ct,
                f"Center exploration nav returned None for target={target}; holding.",
            )
            return True
        self._nav_dbg(ct, f"Center exploration move_dir={move_dir.name} target={target}")
        return self._road_then_move(ct, move_dir)

    def _next_nav_move(
        self,
        ct: Controller,
        nav: TangentNav,
        nav_target_attr: str,
        target: tuple[int, int],
    ) -> Direction | None:
        current_target = getattr(self, nav_target_attr)
        cur = ct.get_position()
        if current_target != target:
            self._nav_dbg(
                ct,
                (
                    f"{nav_target_attr} retarget from {current_target} to {target} "
                    f"start=({cur.x},{cur.y})"
                ),
            )
            nav.set_target(target[0], target[1], cur.x, cur.y)
            setattr(self, nav_target_attr, target)
        move_dir = nav.next_move(ct)
        self._nav_dbg(
            ct,
            (
                f"{nav_target_attr} next_move -> "
                f"{move_dir.name if move_dir else None} toward {target}"
            ),
        )
        return move_dir

    def _visible_ores_from_scan(
        self,
        ct: Controller,
        symmetry_analyzer: Any | None,
    ) -> set[tuple[int, int]]:
        visible: set[tuple[int, int]] = set()
        map_history = getattr(symmetry_analyzer, "map_history", None)
        if isinstance(map_history, dict):
            known_ore_tiles = 0
            for (x, y), env in map_history.items():
                if env not in ORE_ENVS:
                    continue
                known_ore_tiles += 1
                ore_pos = Position(x, y)
                if ct.is_in_vision(ore_pos):
                    visible.add((x, y))
            self._nav_dbg(
                ct,
                (
                    "Ore scan via map_history "
                    f"known_ore_tiles={known_ore_tiles} visible_now={len(visible)}"
                ),
            )
            return visible

        nearby_tiles = 0
        for tile in ct.get_nearby_tiles():
            nearby_tiles += 1
            try:
                env = ct.get_tile_env(tile)
            except Exception:
                continue
            if env in ORE_ENVS:
                visible.add((tile.x, tile.y))
        self._nav_dbg(
            ct,
            (
                "Ore scan via nearby tiles "
                f"nearby_count={nearby_tiles} visible_now={len(visible)}"
            ),
        )
        return visible

    def _select_reachable_ore(
        self,
        ct: Controller,
        my_pos: Position,
        visible_ores: set[tuple[int, int]],
        map_history: dict[tuple[int, int], Environment] | None,
    ) -> tuple[int, int] | None:
        best_target: tuple[int, int] | None = None
        best_dist_sq: int | None = None
        self._nav_dbg(
            ct,
            (
                f"Ore selection start visible_count={len(visible_ores)} "
                f"from=({my_pos.x},{my_pos.y})"
            ),
        )
        for ox, oy in visible_ores:
            self._nav_dbg(ct, f"Evaluating ore candidate ({ox},{oy})")
            if self._is_ore_blacklisted(ct, (ox, oy)):
                self._nav_dbg(ct, f"Skipping blacklisted ore ({ox},{oy}).")
                continue
            ore_pos = Position(ox, oy)
            if self._ore_has_completed_extractor(ct, ore_pos):
                self._nav_dbg(
                    ct,
                    f"Rejecting ore ({ox},{oy}) reason=completed_extractor_present",
                )
                continue
            blocking_type = self._ore_blocking_structure_type(ct, ore_pos)
            if blocking_type is not None:
                self._nav_dbg(
                    ct,
                    f"Rejecting ore ({ox},{oy}) reason=blocked_by_{blocking_type}",
                )
                continue
            has_step = self._has_nav_step_to_ore(ct, ore_pos, map_history)
            if not has_step:
                self._nav_dbg(ct, f"Rejecting ore ({ox},{oy}) reason=no_nav_step")
                continue
            dist_sq = (my_pos.x - ox) ** 2 + (my_pos.y - oy) ** 2
            self._nav_dbg(
                ct,
                f"Ore candidate ({ox},{oy}) accepted dist_sq={dist_sq}",
            )
            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_target = (ox, oy)
                self._nav_dbg(
                    ct,
                    f"Ore candidate ({ox},{oy}) is new best dist_sq={best_dist_sq}",
                )
        self._nav_dbg(
            ct,
            f"Ore selection result best_target={best_target} best_dist_sq={best_dist_sq}",
        )
        return best_target

    def _has_nav_step_to_ore(
        self,
        ct: Controller,
        ore_pos: Position,
        map_history: dict[tuple[int, int], Environment] | None,
    ) -> bool:
        my_pos = ct.get_position()
        if self._in_action_radius(my_pos, ore_pos):
            return True
        probe = TangentNav()
        if isinstance(map_history, dict):
            probe.attach_terrain_memory(map_history)
        probe.set_target(ore_pos.x, ore_pos.y, my_pos.x, my_pos.y)
        probe_move = probe.next_move(ct)
        self._nav_dbg(
            ct,
            (
                f"Probe nav toward ore=({ore_pos.x},{ore_pos.y}) "
                f"from=({my_pos.x},{my_pos.y}) move={probe_move.name if probe_move else None}"
            ),
        )
        return probe_move is not None

    def _build_generator_on_ore(
        self,
        ct: Controller,
        ore_pos: Position,
    ) -> Literal["built", "waiting_money", "blocked", "cooldown"]:
        self._clear_ore_build_obstructions(ct, ore_pos)

        if self._ore_has_completed_extractor(ct, ore_pos):
            return "blocked"
        if self._ore_blocking_structure_type(ct, ore_pos) is not None:
            return "blocked"
        if ct.get_action_cooldown() != 0:
            return "cooldown"

        affordable_extractor, _, _ = get_cost_affordability(ct, "get_harvester_cost")
        if not affordable_extractor:
            return "waiting_money"

        can_build_generator = getattr(ct, "can_build_generator", None)
        build_generator = getattr(ct, "build_generator", None)
        if callable(can_build_generator) and callable(build_generator):
            if can_build_generator(ore_pos):
                build_generator(ore_pos)
                return "built"

        if ct.can_build_harvester(ore_pos):
            ct.build_harvester(ore_pos)
            return "built"
        return "blocked"

    def _roll_post_harvester_return_mode(self, ct: Controller) -> None:
        chance_percent = max(0, min(100, POST_HARVESTER_GREEDY_RETURN_CHANCE_PERCENT))
        roll = random.randrange(100)
        self._greedy_return_no_join_merge = roll < chance_percent
        self._nav_dbg(
            ct,
            (
                "Post-harvester return mode roll "
                f"chance={chance_percent}% roll={roll} "
                f"greedy_no_join_merge={self._greedy_return_no_join_merge}"
            ),
        )

    def _select_bridge_target_toward_core(
        self,
        ct: Controller,
        start_pos: Position,
        core_pos: tuple[int, int],
        allow_chain_join: bool = True,
        allow_merge_with_existing_return_path: bool = True,
    ) -> Position | None:
        core = Position(core_pos[0], core_pos[1])
        candidates: list[Position] = []
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                dist_sq = dx * dx + dy * dy
                if dist_sq == 0 or dist_sq > 9:
                    continue
                tx = start_pos.x + dx
                ty = start_pos.y + dy
                if not (0 <= tx < ct.get_map_width() and 0 <= ty < ct.get_map_height()):
                    continue
                pos = Position(tx, ty)
                candidates.append(pos)
        if not candidates:
            return None

        if allow_chain_join:
            join_target = self._select_nearest_visible_friendly_chain_target(
                ct=ct,
                start_pos=start_pos,
                core=core,
                candidates=candidates,
            )
            if join_target is not None:
                self._nav_dbg(
                    ct,
                    (
                        "Selected nearby friendly chain join target "
                        f"({join_target.x},{join_target.y}) from start "
                        f"({start_pos.x},{start_pos.y})"
                    ),
                )
                return join_target

        candidates.sort(
            key=lambda p: (
                p.distance_squared(core),
                -start_pos.distance_squared(p),
                p.x,
                p.y,
            )
        )
        for cand in candidates:
            if self._is_valid_bridge_target_tile(
                ct,
                cand,
                allow_merge_with_existing_return_path=(
                    allow_merge_with_existing_return_path
                ),
            ):
                return cand
        return None

    def _select_nearest_visible_friendly_chain_target(
            self,
            ct: Controller,
            start_pos: Position,
            core: Position,
            candidates: list[Position],
        ) -> Position | None:
            chain_candidates: list[tuple[int, int, int, int, Position]] = []
            start_dist_to_core = start_pos.distance_squared(core)

            for cand in candidates:
                if not ct.is_in_vision(cand):
                    continue
                try:
                    building_id = ct.get_tile_building_id(cand)
                except Exception:
                    continue
                if building_id is None:
                    continue
                if ct.get_team(building_id) != ct.get_team():
                    continue
                if ct.get_entity_type(building_id) not in (
                    EntityType.BRIDGE,
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                ):
                    continue
                if not self._is_valid_bridge_target_tile(ct, cand):
                    continue
                    
                cand_dist_to_core = cand.distance_squared(core)
                
                # Prevent pointing backwards: only connect if it brings us closer to the core
                if cand_dist_to_core >= start_dist_to_core:
                    continue

                chain_candidates.append(
                    (
                        start_pos.distance_squared(cand),
                        cand_dist_to_core,
                        cand.x,
                        cand.y,
                        cand,
                    )
                )

            if not chain_candidates:
                return None
                
            # Prioritize progress to core (c[1]) over immediate proximity to bot (c[0])
            chain_candidates.sort(key=lambda c: (c[1], c[0], c[2], c[3]))
            return chain_candidates[0][4]

    def _is_valid_bridge_target_tile(
        self,
        ct: Controller,
        pos: Position,
        allow_merge_with_existing_return_path: bool = True,
    ) -> bool:
        if self._is_diagonal_adjacent_to_extractor(ct, pos):
            return False
        if self._is_on_friendly_core(ct, pos):
            return True
        if (
            not allow_merge_with_existing_return_path
            and self._is_on_friendly_return_path(ct, pos)
        ):
            return False
        building_id = ct.get_tile_building_id(pos)
        if building_id is not None:
            return ct.get_entity_type(building_id) in _PASSABLE_BUILDINGS
        if self._has_marker_at(ct, pos):
            return True
        try:
            return ct.get_tile_env(pos) == Environment.EMPTY
        except Exception:
            return False

    @staticmethod
    def _is_diagonal_adjacent_to_extractor(ct: Controller, pos: Position) -> bool:
        generator_type = getattr(EntityType, "GENERATOR", None)
        extractor_types = {EntityType.HARVESTER}
        if generator_type is not None:
            extractor_types.add(generator_type)

        width = ct.get_map_width()
        height = ct.get_map_height()
        diagonals = ((1, 1), (1, -1), (-1, 1), (-1, -1))
        for dx, dy in diagonals:
            check = Position(pos.x + dx, pos.y + dy)
            if not (0 <= check.x < width and 0 <= check.y < height):
                continue
            if not ct.is_in_vision(check):
                continue
            building_id = ct.get_tile_building_id(check)
            if building_id is None:
                continue
            if ct.get_entity_type(building_id) in extractor_types:
                return True
        return False

    @staticmethod
    def _has_marker_at(ct: Controller, pos: Position) -> bool:
        for entity_id in ct.get_nearby_entities():
            if ct.get_entity_type(entity_id) != EntityType.MARKER:
                continue
            if ct.get_position(entity_id) == pos:
                return True
        return False

    def _finish_return_cycle(self) -> None:
        self.agent_phase = "SEEK_ORE"
        self._post_bridge_target = None
        self._return_nav_target = None
        self._return_nav = TangentNav()
        self._greedy_return_no_join_merge = False

    @staticmethod
    def _is_on_friendly_return_path(ct: Controller, pos: Position) -> bool:
        try:
            building_id = ct.get_tile_building_id(pos)
        except Exception:
            return False
        if building_id is None:
            return False
        if ct.get_team(building_id) != ct.get_team():
            return False
        return ct.get_entity_type(building_id) in (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
        )

    @staticmethod
    def _is_on_friendly_core(ct: Controller, pos: Position) -> bool:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        return (
            ct.get_entity_type(building_id) == EntityType.CORE
            and ct.get_team(building_id) == ct.get_team()
        )

    @staticmethod
    def _is_on_friendly_bridge(ct: Controller, pos: Position) -> bool:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        return (
            ct.get_entity_type(building_id) == EntityType.BRIDGE
            and ct.get_team(building_id) == ct.get_team()
        )

    @staticmethod
    def _ore_has_completed_extractor(ct: Controller, ore_pos: Position) -> bool:
        if not ct.is_in_vision(ore_pos):
            return False
        try:
            building_id = ct.get_tile_building_id(ore_pos)
        except Exception:
            return False
        if building_id is None:
            return False
        try:
            b_type = ct.get_entity_type(building_id)
        except Exception:
            return False
        if b_type == EntityType.HARVESTER:
            return True
        generator_type = getattr(EntityType, "GENERATOR", None)
        return generator_type is not None and b_type == generator_type

    @staticmethod
    def _ore_blocking_structure_type(ct: Controller, ore_pos: Position):
        if not ct.is_in_vision(ore_pos):
            return None
        try:
            building_id = ct.get_tile_building_id(ore_pos)
        except Exception:
            return None
        if building_id is None:
            return None
        b_type = ct.get_entity_type(building_id)
        if b_type == EntityType.ROAD:
            return None
        return b_type

    @staticmethod
    def _ore_has_enemy_road(ct: Controller, ore_pos: Position) -> bool:
        if not ct.is_in_vision(ore_pos):
            return False
        try:
            building_id = ct.get_tile_building_id(ore_pos)
        except Exception:
            return False
        if building_id is None:
            return False
        if ct.get_entity_type(building_id) != EntityType.ROAD:
            return False
        return ct.get_team(building_id) != ct.get_team()

    def _try_attack_underfoot_enemy_road(self, ct: Controller, my_pos: Position) -> bool:
        building_id = ct.get_tile_building_id(my_pos)
        if building_id is None:
            return False

        if ct.get_entity_type(building_id) != EntityType.ROAD:
            return False
        if ct.get_team(building_id) == ct.get_team():
            return False

        can_attack = getattr(ct, "can_attack", None)
        attack = getattr(ct, "attack", None)
        if callable(can_attack) and callable(attack) and can_attack(my_pos):
            attack(my_pos)
            self._nav_dbg(
                ct,
                (
                    "On enemy road and attacked underfoot before bridge build "
                    f"at ({my_pos.x},{my_pos.y}) via attack()."
                ),
            )
            return True

        can_fire = getattr(ct, "can_fire", None)
        fire = getattr(ct, "fire", None)
        if callable(can_fire) and callable(fire) and can_fire(my_pos):
            fire(my_pos)
            self._nav_dbg(
                ct,
                (
                    "On enemy road and attacked underfoot before bridge build "
                    f"at ({my_pos.x},{my_pos.y}) via fire()."
                ),
            )
            return True

        self._nav_dbg(
            ct,
            (
                "On enemy road underfoot but cannot attack yet before bridge build "
                f"at ({my_pos.x},{my_pos.y})."
            ),
        )
        return True

    def _handle_enemy_road_on_ore(self, ct: Controller, ore_pos: Position) -> bool:
        """
        If ore is blocked by an enemy road:
        1) step onto ore,
        2) attack road while standing on ore,
        3) let normal cardinal-align/build flow continue next.
        """
        if not self._ore_has_enemy_road(ct, ore_pos):
            return False

        my_pos = ct.get_position()
        if my_pos != ore_pos:
            if ct.get_move_cooldown() != 0:
                self._nav_dbg(
                    ct,
                    (
                        "Enemy road on ore; waiting to step onto ore "
                        f"move_cd={ct.get_move_cooldown()}"
                    ),
                )
                return True

            move_dir = my_pos.direction_to(ore_pos)
            if move_dir != Direction.CENTRE and ct.can_move(move_dir):
                ct.move(move_dir)
                self._nav_dbg(
                    ct,
                    (
                        f"Enemy road on ore; stepped onto ore via {move_dir.name} "
                        f"ore=({ore_pos.x},{ore_pos.y})"
                    ),
                )
                return True

            self._nav_dbg(
                ct,
                (
                    "Enemy road on ore; cannot step onto ore this turn "
                    f"from=({my_pos.x},{my_pos.y}) ore=({ore_pos.x},{ore_pos.y})"
                ),
            )
            return True

        if ct.get_action_cooldown() != 0:
            self._nav_dbg(
                ct,
                (
                    "Standing on enemy road ore; waiting to attack "
                    f"action_cd={ct.get_action_cooldown()}"
                ),
            )
            return True

        can_attack = getattr(ct, "can_attack", None)
        attack = getattr(ct, "attack", None)
        if callable(can_attack) and callable(attack) and can_attack(ore_pos):
            attack(ore_pos)
            self._nav_dbg(
                ct,
                f"Attacked enemy road on ore=({ore_pos.x},{ore_pos.y}) via attack().",
            )
            return True

        can_fire = getattr(ct, "can_fire", None)
        fire = getattr(ct, "fire", None)
        if callable(can_fire) and callable(fire) and can_fire(ore_pos):
            fire(ore_pos)
            self._nav_dbg(
                ct,
                f"Attacked enemy road on ore=({ore_pos.x},{ore_pos.y}) via fire().",
            )
            return True

        self._nav_dbg(
            ct,
            (
                "Standing on enemy road ore but cannot attack this turn "
                f"ore=({ore_pos.x},{ore_pos.y})"
            ),
        )
        return True

    @staticmethod
    def _in_action_radius(my_pos: Position, target: Position) -> bool:
        dx = my_pos.x - target.x
        dy = my_pos.y - target.y
        return dx * dx + dy * dy <= ACTION_RADIUS_SQ

    def _road_then_move(self, ct: Controller, move_dir: Direction) -> bool:
        my_pos = ct.get_position()
        move_pos = ct.get_position().add(move_dir)
        self._nav_dbg(
            ct,
            (
                f"road_then_move start from=({my_pos.x},{my_pos.y}) "
                f"dir={move_dir.name} to=({move_pos.x},{move_pos.y}) "
                f"move_cd={ct.get_move_cooldown()} action_cd={ct.get_action_cooldown()}"
            ),
        )
        if not ct.is_tile_passable(move_pos):
            has_friendly_marker = any(
                ct.get_entity_type(eid) == EntityType.MARKER
                and ct.get_team(eid) == ct.get_team()
                and ct.get_position(eid) == move_pos
                for eid in ct.get_nearby_entities()
            )
            if not has_friendly_marker:
                affordable_road, _, _ = get_cost_affordability(ct, "get_road_cost")
                if not affordable_road:
                    # Hold position and save for road.
                    self._nav_dbg(
                        ct,
                        (
                            f"road_then_move blocked at ({move_pos.x},{move_pos.y}); "
                            "road unaffordable, holding."
                        ),
                    )
                    return True
                if ct.get_action_cooldown() == 0 and ct.can_build_road(move_pos):
                    ct.build_road(move_pos)
                    self._nav_dbg(
                        ct,
                        f"Built road at ({move_pos.x},{move_pos.y}) before moving.",
                    )
                    return True

        if ct.get_move_cooldown() == 0 and ct.can_move(move_dir):
            ct.move(move_dir)
            new_pos = ct.get_position()
            self._nav_dbg(
                ct,
                f"Move succeeded dir={move_dir.name} new_pos=({new_pos.x},{new_pos.y})",
            )
            return True
        self._nav_dbg(
            ct,
            (
                f"Move failed dir={move_dir.name} move_cd={ct.get_move_cooldown()} "
                f"can_move={ct.can_move(move_dir)}"
            ),
        )
        return False

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
    def _clear_ore_build_obstructions(ct: Controller, ore_pos: Position) -> bool:
        acted = False

        building_id = ct.get_tile_building_id(ore_pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            b_team = ct.get_team(building_id)
            if (
                b_team == ct.get_team()
                and b_type == EntityType.ROAD
                and ct.can_destroy(ore_pos)
            ):
                ct.destroy(ore_pos)
                acted = True

        if BridgeBuilder._has_friendly_marker_at(ct, ore_pos) and ct.can_destroy(ore_pos):
            ct.destroy(ore_pos)
            acted = True

        return acted

    @staticmethod
    def _has_friendly_marker_at(ct: Controller, pos: Position) -> bool:
        for entity_id in ct.get_nearby_entities():
            if ct.get_entity_type(entity_id) != EntityType.MARKER:
                continue
            if ct.get_team(entity_id) != ct.get_team():
                continue
            if ct.get_position(entity_id) == pos:
                return True
        return False

    def _start_post_build_alignment(self, ore_pos: Position) -> None:
        self._post_build_align_ore_target = (ore_pos.x, ore_pos.y)

    def _run_post_build_cardinal_alignment(self, ct: Controller) -> bool:
        if self._post_build_align_ore_target is None:
            return True

        ox, oy = self._post_build_align_ore_target
        ore_pos = Position(ox, oy)
        my_pos = ct.get_position()
        if self._is_adjacent_cardinal(my_pos, ore_pos):
            self._post_build_align_ore_target = None
            self.agent_phase = "RETURN_CORE"
            return True

        moved = self._move_to_cardinal_adjacent_tile(ct, ore_pos)
        if moved:
            new_pos = ct.get_position()
            if self._is_adjacent_cardinal(new_pos, ore_pos):
                self._post_build_align_ore_target = None
                self.agent_phase = "RETURN_CORE"
            return True

        # Hold if no legal cardinal-adjacent move is currently possible.
        return True

    def _move_to_cardinal_adjacent_tile(self, ct: Controller, ore_pos: Position) -> bool:
        my_pos = ct.get_position()
        self._nav_dbg(
            ct,
            (
                f"Cardinal-align start pos=({my_pos.x},{my_pos.y}) "
                f"ore=({ore_pos.x},{ore_pos.y})"
            ),
        )
        for move_dir in _CARDINAL_DIRECTIONS:
            nxt = my_pos.add(move_dir)
            if not self._is_adjacent_cardinal(nxt, ore_pos):
                self._nav_dbg(
                    ct,
                    f"Cardinal-align skip dir={move_dir.name} next=({nxt.x},{nxt.y}) not adjacent.",
                )
                continue

            try:
                if ct.get_tile_env(nxt) == Environment.WALL:
                    self._nav_dbg(
                        ct,
                        f"Cardinal-align skip dir={move_dir.name} due to wall.",
                    )
                    continue
                b_id = ct.get_tile_building_id(nxt)
                if b_id is not None:
                    b_type = ct.get_entity_type(b_id)
                    if b_type not in (
                        EntityType.ROAD,
                        EntityType.BRIDGE,
                        EntityType.CORE,
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                    ):
                        self._nav_dbg(
                            ct,
                            (
                                f"Cardinal-align skip dir={move_dir.name} "
                                f"blocked by building={b_type}."
                            ),
                        )
                        continue
            except Exception:
                self._nav_dbg(
                    ct,
                    f"Cardinal-align exception probing dir={move_dir.name}; skipping.",
                )
                continue

            if self._road_then_move(ct, move_dir):
                self._nav_dbg(
                    ct,
                    f"Cardinal-align moved dir={move_dir.name}.",
                )
                return True

        self._nav_dbg(ct, "Cardinal-align found no legal move.")
        return False

    @staticmethod
    def _is_adjacent_cardinal(a: Position, b: Position) -> bool:
        return abs(a.x - b.x) + abs(a.y - b.y) == 1

    @staticmethod
    def _is_adjacent_diagonal(a: Position, b: Position) -> bool:
        return abs(a.x - b.x) == 1 and abs(a.y - b.y) == 1

    def _should_run_diagonal_ore_alignment(self, my_pos: Position, ore_pos: Position) -> bool:
        ore_target = (ore_pos.x, ore_pos.y)
        if self._is_adjacent_diagonal(my_pos, ore_pos):
            return True
        if self._diag_align_ore_target != ore_target:
            return False
        return not self._is_adjacent_cardinal(my_pos, ore_pos)

    def _run_diagonal_ore_alignment(self, ct: Controller, ore_pos: Position) -> bool:
        my_pos = ct.get_position()
        ore_target = (ore_pos.x, ore_pos.y)
        if self._diag_align_ore_target != ore_target:
            self._diag_align_ore_target = ore_target
            self._diag_align_nav_target = None
            self._diag_align_nav = TangentNav()

        if self._is_adjacent_cardinal(my_pos, ore_pos):
            self._clear_diagonal_alignment_state()
            return False

        open_tiles = self._open_cardinal_ore_tiles_in_vision(ct, ore_pos)
        if not open_tiles:
            self._blacklist_current_ore(
                ct,
                reason=(
                    "diagonal ore alignment found no open cardinal ore-adjacent tiles "
                    "in vision"
                ),
            )
            return True

        targets = sorted(
            open_tiles,
            key=lambda tile: (
                (my_pos.x - tile[0]) ** 2 + (my_pos.y - tile[1]) ** 2,
                tile[0],
                tile[1],
            ),
        )
        if self._diag_align_nav_target in open_tiles:
            preferred = self._diag_align_nav_target
            targets = [preferred, *[tile for tile in targets if tile != preferred]]

        for target in targets:
            move_dir = self._next_nav_move(
                ct,
                nav=self._diag_align_nav,
                nav_target_attr="_diag_align_nav_target",
                target=target,
            )
            if move_dir is None:
                continue
            self._nav_dbg(
                ct,
                (
                    "Diagonal ore-align bugnav move "
                    f"dir={move_dir.name} toward=({target[0]},{target[1]}) "
                    f"ore=({ore_pos.x},{ore_pos.y})"
                ),
            )
            self._road_then_move(ct, move_dir)
            return True

        self._blacklist_current_ore(
            ct,
            reason=(
                "diagonal ore alignment found open ore-adjacent tiles but no bugnav "
                "step toward any target"
            ),
        )
        return True

    def _open_cardinal_ore_tiles_in_vision(
        self, ct: Controller, ore_pos: Position
    ) -> set[tuple[int, int]]:
        open_tiles: set[tuple[int, int]] = set()
        for move_dir in _CARDINAL_DIRECTIONS:
            cand = ore_pos.add(move_dir)
            if self._is_open_stand_tile_in_vision(ct, cand):
                open_tiles.add((cand.x, cand.y))
        return open_tiles

    @staticmethod
    def _is_open_stand_tile_in_vision(ct: Controller, pos: Position) -> bool:
        if not ct.is_in_vision(pos):
            return False
        try:
            if ct.get_tile_env(pos) == Environment.WALL:
                return False
            building_id = ct.get_tile_building_id(pos)
            if building_id is not None:
                b_type = ct.get_entity_type(building_id)
                own_core = b_type == EntityType.CORE and ct.get_team(building_id) == ct.get_team()
                if not own_core and b_type not in _PASSABLE_BUILDINGS:
                    return False
            builder_id = ct.get_tile_builder_bot_id(pos)
            if builder_id is not None:
                return False
        except Exception:
            return False
        return True

    def _clear_diagonal_alignment_state(self) -> None:
        self._diag_align_nav = TangentNav()
        self._diag_align_nav_target = None
        self._diag_align_ore_target = None

    def _cleanup_ore_blacklist(self, ct: Controller) -> None:
        curr_round = ct.get_current_round()
        prev_size = len(self._ore_blacklist)
        self._ore_blacklist = {
            ore: expiry for ore, expiry in self._ore_blacklist.items() if expiry > curr_round
        }
        if prev_size != len(self._ore_blacklist):
            self._nav_dbg(
                ct,
                (
                    f"Ore blacklist cleanup {prev_size}->{len(self._ore_blacklist)} "
                    f"at round={curr_round}"
                ),
            )

    def _is_ore_blacklisted(self, ct: Controller, ore: tuple[int, int]) -> bool:
        expiry = self._ore_blacklist.get(ore)
        return expiry is not None and expiry > ct.get_current_round()

    def _blacklist_current_ore(self, ct: Controller, reason: str) -> None:
        if self.ore_target is None:
            return
        expiry = ct.get_current_round() + _ORE_TARGET_BLACKLIST_ROUNDS
        self._ore_blacklist[self.ore_target] = expiry
        self._nav_dbg(
            ct,
            (
                f"Blacklisting ore {self.ore_target} until round={expiry}. "
                f"reason={reason}"
            ),
        )
        self._clear_ore_target()

    def _clear_ore_target(self) -> None:
        self.ore_target = None
        self._ore_nav_target = None
        self._ore_nav = TangentNav()
        self._clear_diagonal_alignment_state()

    def _handle_pending_launcher_after_bridge(self, ct: Controller) -> bool:
        if self._launcher_pending_anchor is None:
            return False

        anchor = Position(
            self._launcher_pending_anchor[0],
            self._launcher_pending_anchor[1],
        )
        my_pos = ct.get_position()
        width = ct.get_map_width()
        height = ct.get_map_height()
        adjacent: list[Position] = []
        for dx, dy in _ADJACENT_DELTAS:
            nx = anchor.x + dx
            ny = anchor.y + dy
            if 0 <= nx < width and 0 <= ny < height:
                adjacent.append(Position(nx, ny))

        if not adjacent:
            self._launcher_pending_anchor = None
            return False

        actionable = [
            pos for pos in adjacent if self._in_action_radius(my_pos, pos)
        ]
        if not actionable:
            self._nav_dbg(
                ct,
                (
                    "Skipping pending defensive launcher: no adjacent anchor tiles "
                    f"in action range from ({my_pos.x},{my_pos.y}) "
                    f"for anchor=({anchor.x},{anchor.y})."
                ),
            )
            self._launcher_pending_anchor = None
            return False

        empty_tiles: list[Position] = []
        friendly_road_tiles: list[Position] = []
        enemy_road_tiles: list[Position] = []
        for pos in actionable:
            building_id = ct.get_tile_building_id(pos)
            if building_id is None:
                empty_tiles.append(pos)
                continue
            if ct.get_entity_type(building_id) != EntityType.ROAD:
                continue
            if ct.get_team(building_id) == ct.get_team():
                friendly_road_tiles.append(pos)
            else:
                enemy_road_tiles.append(pos)

        # Priority 1: any empty adjacent tile.
        if empty_tiles:
            affordable, _, _ = get_cost_affordability(ct, "get_launcher_cost")
            if not affordable or ct.get_action_cooldown() != 0:
                return False
            for pos in empty_tiles:
                if ct.can_build_launcher(pos):
                    ct.build_launcher(pos)
                    self._launcher_pending_anchor = None
                    self._nav_dbg(
                        ct,
                        (
                            "Built defensive launcher adjacent to bridge anchor "
                            f"at ({pos.x},{pos.y}) for anchor=({anchor.x},{anchor.y})."
                        ),
                    )
                    return True
            return False

        # Priority 2: no empty tile, clear friendly road first.
        if friendly_road_tiles:
            if ct.get_action_cooldown() != 0:
                return False
            for pos in friendly_road_tiles:
                if ct.can_destroy(pos):
                    ct.destroy(pos)
                    self._nav_dbg(
                        ct,
                        (
                            "Destroyed friendly road to free launcher tile "
                            f"at ({pos.x},{pos.y}) for anchor=({anchor.x},{anchor.y})."
                        ),
                    )
                    return True
            return False

        # Priority 3: no empty/friendly road, attack enemy road first.
        if enemy_road_tiles:
            if ct.get_action_cooldown() != 0:
                return False
            for pos in enemy_road_tiles:
                if self._attack_position(ct, pos):
                    self._nav_dbg(
                        ct,
                        (
                            "Attacked enemy road to free launcher tile "
                            f"at ({pos.x},{pos.y}) for anchor=({anchor.x},{anchor.y})."
                        ),
                    )
                    return True
            return False

        # Priority 4: nothing usable around anchor; skip and continue normal logic.
        self._launcher_pending_anchor = None
        return False

    @staticmethod
    def _attack_position(ct: Controller, target: Position) -> bool:
        can_attack = getattr(ct, "can_attack", None)
        attack = getattr(ct, "attack", None)
        if callable(can_attack) and callable(attack) and can_attack(target):
            attack(target)
            return True

        can_fire = getattr(ct, "can_fire", None)
        fire = getattr(ct, "fire", None)
        if callable(can_fire) and callable(fire) and can_fire(target):
            fire(target)
            return True

        return False

    def _nav_dbg(self, ct: Controller, msg: str) -> None:
        if not self._nav_dbg_enabled(ct):
            return
        current_round = ct.get_current_round()
        pos = ct.get_position()
        print(
            (
                f"[R{current_round}][ID={ct.get_id()}][BridgeNav][{pos.x},{pos.y}] "
                f"{msg}"
            ),
            file=sys.stderr,
        )

    def _nav_dbg_enabled(self, ct: Controller) -> bool:
        if not self._NAV_DEBUG:
            return False
        current_round = ct.get_current_round()
        in_round_window = (
            self._NAV_DEBUG_START_ROUND <= current_round <= self._NAV_DEBUG_END_ROUND
        )
        if not in_round_window:
            return False
        if not self._NAV_DEBUG_ONLY_TARGET_ID:
            return True
        return ct.get_id() == self._NAV_DEBUG_TARGET_UNIT_ID
