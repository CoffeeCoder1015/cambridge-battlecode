from typing import Any, Literal

from cambc import Controller, Direction, EntityType, Environment, Position

from ..Movement.TangentNav import TangentNav
from ..helper import get_cost_affordability

ACTION_RADIUS_SQ = 2
ORE_ENVS = (Environment.ORE_TITANIUM,)
_PASSABLE_BUILDINGS = (
    EntityType.ROAD,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
)

Phase = Literal["SEEK_ORE", "RETURN_CORE"]


class BridgeBuilder:
    def __init__(self) -> None:
        self.ore_target: tuple[int, int] | None = None
        self.agent_phase: Phase = "SEEK_ORE"
        self._ore_nav = TangentNav()
        self._ore_nav_target: tuple[int, int] | None = None
        self._return_nav = TangentNav()
        self._return_nav_target: tuple[int, int] | None = None
        self._post_bridge_target: tuple[int, int] | None = None

    def run(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
        symmetry_analyzer: Any | None,
    ) -> bool:
        map_history = getattr(symmetry_analyzer, "map_history", None)
        if isinstance(map_history, dict):
            self._ore_nav.attach_terrain_memory(map_history)
            self._return_nav.attach_terrain_memory(map_history)

        if self.agent_phase == "RETURN_CORE":
            return self._run_return_core(ct, core_pos)

        my_pos = ct.get_position()
        visible_ores = self._visible_ores_from_scan(ct, symmetry_analyzer)

        if self.ore_target is not None:
            ore_pos = Position(self.ore_target[0], self.ore_target[1])
            if (
                self.ore_target not in visible_ores
                or self._ore_has_completed_extractor(ct, ore_pos)
                or self._ore_blocking_structure_type(ct, ore_pos) is not None
            ):
                self._clear_ore_target()

        if self.ore_target is None:
            self.ore_target = self._select_reachable_ore(ct, my_pos, visible_ores, map_history)

        if self.ore_target is None:
            return self._run_center_exploration(ct)

        ore_pos = Position(self.ore_target[0], self.ore_target[1])
        if self._in_action_radius(my_pos, ore_pos):
            build_result = self._build_generator_on_ore(ct, ore_pos)
            if build_result == "built":
                self._clear_ore_target()
                self.agent_phase = "RETURN_CORE"
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
            self._clear_ore_target()
            return True
        return self._road_then_move(ct, move_dir)

    def _run_return_core(self, ct: Controller, core_pos: tuple[int, int] | None) -> bool:
        if core_pos is None:
            return True

        my_pos = ct.get_position()
        if self._is_on_friendly_core(ct, my_pos):
            self._finish_return_cycle()
            return True

        # Match old bridge cycle: after placing a bridge, move to that endpoint before
        # selecting another bridge segment.
        if self._post_bridge_target is not None:
            tx, ty = self._post_bridge_target
            if (my_pos.x, my_pos.y) == (tx, ty):
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
                    return True
                self._road_then_move(ct, move_dir)
                new_pos = ct.get_position()
                if (new_pos.x, new_pos.y) == (tx, ty):
                    self._post_bridge_target = None
                    self._return_nav_target = None
                return True

        bridge_target = self._select_bridge_target_toward_core(
            ct=ct,
            start_pos=my_pos,
            core_pos=core_pos,
        )
        if bridge_target is None:
            move_target = core_pos
        else:
            # Match old bridge-cycle behavior: wait until bridge placement is possible.
            if ct.get_action_cooldown() != 0:
                return True

            affordable_bridge, _, _ = get_cost_affordability(ct, "get_bridge_cost")
            if not affordable_bridge:
                # Hold position and save for bridge to maintain chain behavior.
                return True

            target_is_existing_return_path = self._is_on_friendly_return_path(
                ct, bridge_target
            )
            self._clear_underfoot_for_bridge(ct, my_pos)

            if ct.can_build_bridge(my_pos, bridge_target):
                ct.build_bridge(my_pos, bridge_target)
                if self._is_on_friendly_core(ct, bridge_target) or target_is_existing_return_path:
                    self._finish_return_cycle()
                    return True
                self._post_bridge_target = (bridge_target.x, bridge_target.y)
                move_target = self._post_bridge_target
            else:
                # Roads/conveyors underfoot can block start tile bridge placement.
                if self._clear_underfoot_for_bridge(ct, my_pos) and ct.can_build_bridge(
                    my_pos, bridge_target
                ):
                    ct.build_bridge(my_pos, bridge_target)
                    if self._is_on_friendly_core(ct, bridge_target) or target_is_existing_return_path:
                        self._finish_return_cycle()
                        return True
                    self._post_bridge_target = (bridge_target.x, bridge_target.y)
                    move_target = self._post_bridge_target
                else:
                    return True

        move_dir = self._next_nav_move(
            ct,
            nav=self._return_nav,
            nav_target_attr="_return_nav_target",
            target=move_target,
        )
        if move_dir is None:
            return True
        return self._road_then_move(ct, move_dir)

    def _run_center_exploration(self, ct: Controller) -> bool:
        target = (ct.get_map_width() // 2, ct.get_map_height() // 2)
        move_dir = self._next_nav_move(
            ct,
            nav=self._ore_nav,
            nav_target_attr="_ore_nav_target",
            target=target,
        )
        if move_dir is None:
            return True
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
            nav.set_target(target[0], target[1], cur.x, cur.y)
            setattr(self, nav_target_attr, target)
        return nav.next_move(ct)

    def _visible_ores_from_scan(
        self,
        ct: Controller,
        symmetry_analyzer: Any | None,
    ) -> set[tuple[int, int]]:
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
        map_history: dict[tuple[int, int], Environment] | None,
    ) -> tuple[int, int] | None:
        best_target: tuple[int, int] | None = None
        best_dist_sq: int | None = None
        for ox, oy in visible_ores:
            ore_pos = Position(ox, oy)
            if self._ore_has_completed_extractor(ct, ore_pos):
                continue
            if self._ore_blocking_structure_type(ct, ore_pos) is not None:
                continue
            if not self._has_nav_step_to_ore(ct, ore_pos, map_history):
                continue
            dist_sq = (my_pos.x - ox) ** 2 + (my_pos.y - oy) ** 2
            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_target = (ox, oy)
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
        return probe.next_move(ct) is not None

    def _build_generator_on_ore(
        self,
        ct: Controller,
        ore_pos: Position,
    ) -> Literal["built", "waiting_money", "blocked", "cooldown"]:
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
        candidates.sort(
            key=lambda p: (
                p.distance_squared(core),
                -start_pos.distance_squared(p),
                p.x,
                p.y,
            )
        )
        for cand in candidates:
            if self._is_valid_bridge_target_tile(ct, cand):
                return cand
        return None

    def _is_valid_bridge_target_tile(self, ct: Controller, pos: Position) -> bool:
        if self._is_on_friendly_core(ct, pos):
            return True
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
    def _in_action_radius(my_pos: Position, target: Position) -> bool:
        dx = my_pos.x - target.x
        dy = my_pos.y - target.y
        return dx * dx + dy * dy <= ACTION_RADIUS_SQ

    @staticmethod
    def _road_then_move(ct: Controller, move_dir: Direction) -> bool:
        move_pos = ct.get_position().add(move_dir)
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
                    return True
                if ct.get_action_cooldown() == 0 and ct.can_build_road(move_pos):
                    ct.build_road(move_pos)
                    return True

        if ct.get_move_cooldown() == 0 and ct.can_move(move_dir):
            ct.move(move_dir)
            return True
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

    def _clear_ore_target(self) -> None:
        self.ore_target = None
        self._ore_nav_target = None
        self._ore_nav = TangentNav()
