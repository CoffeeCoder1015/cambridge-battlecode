import random
import sys
from typing import Any

from cambc import Controller, Direction, EntityType, Environment, Position
from ..Movement.TangentBug import TangentBug

ORE_ENVS = (Environment.ORE_TITANIUM,)
ACTION_RADIUS_SQ = 2
BRIDGE_BUILDER_DEBUG_PRINTS = True
CARDINAL_DIRECTIONS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)


class BridgeBuilder:
    def __init__(self) -> None:
        self.debug_prints = BRIDGE_BUILDER_DEBUG_PRINTS
        self.ore_target: tuple[int, int] | None = None
        self._ore_nav_target: tuple[int, int] | None = None
        self._ore_nav = TangentBug()
        self._remembered_ore_target: tuple[int, int] | None = None
        self._remembered_ore_nav_target: tuple[int, int] | None = None
        self._remembered_ore_nav = TangentBug()
        self._post_build_align_ore_target: tuple[int, int] | None = None
        self._post_generator_bridge_pending = False
        self._post_bridge_target: tuple[int, int] | None = None
        self._resume_random_after_bridge = False
        self._post_bridge_nav = TangentBug()

    def main(
        self,
        ct: Controller,
        known_symmetry=None,
        core_pos: tuple[int, int] | None = None,
        symmetry_analyzer: Any | None = None,
    ) -> bool:
        del known_symmetry
        my_pos = ct.get_position()
        self._log(
            ct,
            (
                f"main pos=({my_pos.x},{my_pos.y}) ore_target={self.ore_target} "
                f"remembered_ore_target={self._remembered_ore_target} "
                f"remembered_nav_target={self._remembered_ore_nav_target} "
                f"post_build_align_ore={self._post_build_align_ore_target} "
                f"post_bridge_target={self._post_bridge_target} "
                f"post_bridge_pending={self._post_generator_bridge_pending} "
                f"resume_random={self._resume_random_after_bridge}"
            ),
        )

        if self._post_build_align_ore_target is not None:
                self._log(ct, "continuing post-build cardinal alignment")
                # If it returns True, it moved. If False, it's aligned, so keep going.
                if self._run_post_build_cardinal_alignment(ct):
                    return True

        if self._remembered_ore_nav_target is not None:
            self._log(ct, "continuing remembered ore navigation")
            return self._advance_remembered_ore_navigation(ct)

        if self._post_bridge_target is not None:
            self._log(ct, "continuing post-bridge navigation")
            return self._advance_post_bridge_navigation(ct, core_pos)

        if self._post_generator_bridge_pending:
            self._log(ct, "running post-generator bridge cycle")
            return self._run_post_generator_bridge(ct, core_pos)

        if self._resume_random_after_bridge:
            self._resume_random_after_bridge = False
            self._clear_primary_ore_target()
            if self._start_remembered_ore_navigation(ct):
                return self._advance_remembered_ore_navigation(ct)
            self._log(ct, "bridge cycle complete at core, re-entering random exploration")
            return self._run_random_fallback(ct)

        visible_ores = self._visible_ores_from_scan(ct, symmetry_analyzer)
        self._log(ct, f"visible ores in scan={len(visible_ores)} {sorted(visible_ores)}")

        if self.ore_target is not None:
            if self.ore_target not in visible_ores:
                self._log(ct, f"dropping ore target {self.ore_target} (no longer visible)")
                self._clear_primary_ore_target()
            elif self._ore_has_completed_extractor(
                ct,
                Position(self.ore_target[0], self.ore_target[1]),
            ):
                self._log(ct, f"dropping ore target {self.ore_target} (already harvested)")
                self._clear_primary_ore_target()
            else:
                blocking_type = self._ore_blocking_structure_type(
                    ct,
                    Position(self.ore_target[0], self.ore_target[1]),
                )
                if blocking_type is not None:
                    self._log(
                        ct,
                        f"dropping ore target {self.ore_target} (blocked by {blocking_type})",
                    )
                    self._clear_primary_ore_target()

        if self.ore_target is None:
            self.ore_target = self._select_reachable_ore(ct, my_pos, visible_ores)
            self._log(ct, f"selected reachable ore target={self.ore_target}")

        self._remember_secondary_ore(ct, my_pos, visible_ores)

        if self.ore_target is None:
            self._log(ct, "no reachable ore, falling back to random exploration")
            return self._run_random_fallback(ct)

        ore_pos = Position(self.ore_target[0], self.ore_target[1])

        if self._in_action_radius(my_pos, ore_pos):
            self._log(ct, f"ore {self.ore_target} in action radius, trying build")
            built = self._build_generator_on_ore(ct, ore_pos)
            if built:
                self._clear_primary_ore_target()
                self._start_post_build_alignment(ct, ore_pos)
            else:
                blocking_type = self._ore_blocking_structure_type(ct, ore_pos)
                if blocking_type is not None:
                    self._log(
                        ct,
                        (
                            f"forfeiting ore {self.ore_target}: "
                            f"blocked by non-road entity {blocking_type}"
                        ),
                    )
                    self._clear_primary_ore_target()
                    return self._run_random_fallback(ct)
                self._log(ct, "generator build not possible this turn")
            # Keep control while in range so fallback movement does not pull us off target.
            return True

        move_dir = self._next_bugnav_move_to_ore(ct, ore_pos)
        if move_dir is None:
            self._log(ct, f"could not bugnav path to ore {self.ore_target}, returning to random")
            self._clear_primary_ore_target()
            return self._run_random_fallback(ct)

        self._log(ct, f"bugnav move toward ore via {move_dir}")
        self._road_then_move(ct, move_dir)
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
        self._log(ct, "symmetry map_history unavailable, using nearby tile scan fallback")
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
        best_dist_sq: int | None = None

        for ox, oy in visible_ores:
            ore_pos = Position(ox, oy)
            if self._ore_has_completed_extractor(ct, ore_pos):
                self._log(ct, f"ore {(ox, oy)} rejected: harvester/generator already present")
                continue
            blocking_type = self._ore_blocking_structure_type(ct, ore_pos)
            if blocking_type is not None:
                self._log(
                    ct,
                    f"ore {(ox, oy)} rejected: blocked by non-road entity {blocking_type}",
                )
                continue
            if not self._has_bugnav_step_to_ore(ct, ore_pos):
                self._log(ct, f"ore {(ox, oy)} rejected: no bugnav route available")
                continue
            dist_sq = (my_pos.x - ox) ** 2 + (my_pos.y - oy) ** 2
            self._log(ct, f"ore {(ox, oy)} candidate dist_sq={dist_sq}")
            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_target = (ox, oy)

        if best_target is not None:
            self._log(ct, f"best ore picked={best_target} with dist_sq={best_dist_sq}")
        return best_target

    def _has_bugnav_step_to_ore(self, ct: Controller, ore_pos: Position) -> bool:
        if self._in_action_radius(ct.get_position(), ore_pos):
            return True
        probe = TangentBug()
        probe.set_target(ore_pos.x, ore_pos.y)
        return probe.next_move(ct) is not None

    def _remember_secondary_ore(
        self,
        ct: Controller,
        my_pos: Position,
        visible_ores: set[tuple[int, int]],
    ) -> None:
        if self.ore_target is None:
            return

        best_alt: tuple[int, int] | None = None
        best_dist_sq: int | None = None

        for ox, oy in visible_ores:
            ore = (ox, oy)
            if ore == self.ore_target:
                continue
            ore_pos = Position(ox, oy)
            if self._ore_has_completed_extractor(ct, ore_pos):
                continue
            if self._ore_blocking_structure_type(ct, ore_pos) is not None:
                continue
            dist_sq = (my_pos.x - ox) ** 2 + (my_pos.y - oy) ** 2
            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_alt = ore

        if best_alt is not None and best_alt != self._remembered_ore_target:
            self._remembered_ore_target = best_alt
            self._log(
                ct,
                (
                    f"remembered secondary ore target={best_alt} "
                    f"while pursuing primary target={self.ore_target}"
                ),
            )

    def _next_bugnav_move_to_ore(self, ct: Controller, ore_pos: Position) -> Direction | None:
        target = (ore_pos.x, ore_pos.y)
        if self._ore_nav_target != target:
            self._ore_nav_target = target
            self._ore_nav.set_target(ore_pos.x, ore_pos.y)
        return self._ore_nav.next_move(ct)

    def _clear_primary_ore_target(self) -> None:
        self.ore_target = None
        self._ore_nav_target = None
        self._ore_nav.reset()

    @staticmethod
    def _in_action_radius(my_pos: Position, target: Position) -> bool:
        dx = my_pos.x - target.x
        dy = my_pos.y - target.y
        return dx * dx + dy * dy <= ACTION_RADIUS_SQ

    def _build_generator_on_ore(self, ct: Controller, ore_pos: Position) -> bool:
        self._clear_ore_build_obstructions(ct, ore_pos)

        if self._ore_has_completed_extractor(ct, ore_pos):
            self._log(ct, f"ore already has harvester/generator at ({ore_pos.x},{ore_pos.y})")
            return False

        blocking_type = self._ore_blocking_structure_type(ct, ore_pos)
        if blocking_type is not None:
            self._log(
                ct,
                (
                    f"cannot build extractor at ({ore_pos.x},{ore_pos.y}); "
                    f"blocked by non-road entity {blocking_type}"
                ),
            )
            return False

        if ct.get_action_cooldown() != 0:
            self._log(ct, f"build blocked by action cooldown={ct.get_action_cooldown()}")
            return False

        can_build_generator = getattr(ct, "can_build_generator", None)
        build_generator = getattr(ct, "build_generator", None)
        if callable(can_build_generator) and callable(build_generator):
            if can_build_generator(ore_pos):
                build_generator(ore_pos)
                self._log(ct, f"built generator at ({ore_pos.x},{ore_pos.y})")
                return True
            self._log(ct, f"generator API available but cannot build at ({ore_pos.x},{ore_pos.y})")

        # Backward-compatible fallback where ore extraction uses harvester API.
        if ct.can_build_harvester(ore_pos):
            ct.build_harvester(ore_pos)
            self._log(ct, f"built harvester at ({ore_pos.x},{ore_pos.y})")
            return True

        self._log(ct, f"cannot build generator/harvester at ({ore_pos.x},{ore_pos.y})")
        return False

    def _ore_has_completed_extractor(self, ct: Controller, ore_pos: Position) -> bool:
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

    def _clear_ore_build_obstructions(self, ct: Controller, ore_pos: Position) -> bool:
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
                self._log(ct, f"cleared friendly road on ore ({ore_pos.x},{ore_pos.y})")

        if self._has_friendly_marker_at(ct, ore_pos) and ct.can_destroy(ore_pos):
            ct.destroy(ore_pos)
            acted = True
            self._log(ct, f"cleared friendly marker on ore ({ore_pos.x},{ore_pos.y})")

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

    @staticmethod
    def _has_marker_at(ct: Controller, pos: Position) -> bool:
        for entity_id in ct.get_nearby_entities():
            if ct.get_entity_type(entity_id) != EntityType.MARKER:
                continue
            if ct.get_position(entity_id) == pos:
                return True
        return False

    def _run_post_generator_bridge(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
    ) -> bool:
        if core_pos is None:
            self._log(ct, "post-generator bridge paused: core_pos unknown")
            return True

        start_pos = ct.get_position()
        self._log(ct, f"bridge-cycle start from ({start_pos.x},{start_pos.y})")
        self._clear_underfoot_for_bridge(ct, start_pos)

        target_pos = self._select_bridge_target_toward_core(
            ct=ct,
            start_pos=start_pos,
            core_pos=core_pos,
        )
        if target_pos is None:
            self._log(ct, "bridge-cycle ended: no bridge target candidate")
            self._clear_post_bridge_state()
            return True

        self._log(ct, f"bridge-cycle target selected=({target_pos.x},{target_pos.y})")
        if ct.get_action_cooldown() != 0:
            self._log(ct, f"bridge build blocked by action cooldown={ct.get_action_cooldown()}")
            return True

        if ct.can_build_bridge(start_pos, target_pos):
            ct.build_bridge(start_pos, target_pos)
            self._log(ct, f"built bridge from ({start_pos.x},{start_pos.y}) to ({target_pos.x},{target_pos.y})")
            if self._is_on_friendly_core(ct, target_pos):
                self._finish_bridge_cycle_to_core(ct)
                return True
            self._post_generator_bridge_pending = False
            self._start_post_bridge_navigation(target_pos)
            self._log(ct, "starting TangentBug movement toward bridge target")
            self._advance_post_bridge_navigation(ct, core_pos)
            return True

        # Some tiles (for example roads) can block bridge placement on the start tile.
        if self._clear_underfoot_for_bridge(ct, start_pos):
            self._log(ct, "cleared underfoot tile and retrying bridge build")
            if ct.can_build_bridge(start_pos, target_pos):
                ct.build_bridge(start_pos, target_pos)
                self._log(
                    ct,
                    f"built bridge after clear from ({start_pos.x},{start_pos.y}) to ({target_pos.x},{target_pos.y})",
                )
                if self._is_on_friendly_core(ct, target_pos):
                    self._finish_bridge_cycle_to_core(ct)
                    return True
                self._post_generator_bridge_pending = False
                self._start_post_bridge_navigation(target_pos)
                self._log(ct, "starting TangentBug movement toward bridge target")
                self._advance_post_bridge_navigation(ct, core_pos)
                return True

        self._log(
            ct,
            f"cannot place bridge from ({start_pos.x},{start_pos.y}) to ({target_pos.x},{target_pos.y}) this turn",
        )
        return True

    def _start_post_bridge_navigation(self, target_pos: Position) -> None:
        self._post_bridge_target = (target_pos.x, target_pos.y)
        self._post_bridge_nav.set_target(target_pos.x, target_pos.y)

    def _advance_post_bridge_navigation(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
    ) -> bool:
        if self._post_bridge_target is None:
            return True

        tx, ty = self._post_bridge_target
        my_pos = ct.get_position()
        self._log(ct, f"post-bridge nav at ({my_pos.x},{my_pos.y}) -> target ({tx},{ty})")
        if (my_pos.x, my_pos.y) == (tx, ty):
            self._log(ct, "arrived at bridge target; triggering next bridge cycle step")
            self._post_bridge_target = None
            self._post_bridge_nav.reset()
            self._post_generator_bridge_pending = True
            return self._run_post_generator_bridge(ct, core_pos)

        if core_pos is None:
            self._log(ct, "post-bridge nav paused: core_pos unknown")
            return True

        if self._post_bridge_nav.target != (tx, ty):
            self._post_bridge_nav.set_target(tx, ty)

        move_dir = self._post_bridge_nav.next_move(ct)
        if move_dir is None:
            self._log(ct, "TangentBug returned no move this turn")
            return True

        self._log(ct, f"TangentBug move direction={move_dir}")
        self._road_then_move(ct, move_dir)

        new_pos = ct.get_position()
        if (new_pos.x, new_pos.y) == (tx, ty):
            self._log(ct, "arrived at bridge target after movement; triggering next bridge cycle step")
            self._post_bridge_target = None
            self._post_bridge_nav.reset()
            self._post_generator_bridge_pending = True
            return self._run_post_generator_bridge(ct, core_pos)
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
        for cand in candidates:
            if self._is_valid_bridge_target_tile(ct, cand):
                self._log(
                    ct,
                    (
                        f"bridge target choice from ({start_pos.x},{start_pos.y}) -> ({cand.x},{cand.y}) "
                        f"out of {len(candidates)} candidates toward core ({core.x},{core.y})"
                    ),
                )
                return cand
            self._log(
                ct,
                f"bridge target rejected ({cand.x},{cand.y}) due to tile type/state",
            )

        self._log(ct, "no valid bridge target candidate after tile-state filtering")
        return None

    def _is_valid_bridge_target_tile(self, ct: Controller, pos: Position) -> bool:
        # Preserve terminal behavior: when target lands on core tile we end bridge cycle.
        if self._is_on_friendly_core(ct, pos):
            return True

        building_id = ct.get_tile_building_id(pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            return b_type in (
                EntityType.ROAD,
                EntityType.BRIDGE,
                EntityType.CONVEYOR,
                EntityType.ARMOURED_CONVEYOR,
            )

        if self._has_marker_at(ct, pos):
            return True

        try:
            env = ct.get_tile_env(pos)
        except Exception:
            return False
        return env == Environment.EMPTY

    def _clear_underfoot_for_bridge(self, ct: Controller, my_pos: Position) -> bool:
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
            self._log(ct, f"cleared underfoot {b_type} at ({my_pos.x},{my_pos.y})")
            return True

        return False

    def _clear_post_bridge_state(self) -> None:
        self._post_generator_bridge_pending = False
        self._post_bridge_target = None
        self._post_bridge_nav.reset()

    def _clear_remembered_ore_navigation(self) -> None:
        self._remembered_ore_nav_target = None
        self._remembered_ore_nav.reset()

    def _start_remembered_ore_navigation(self, ct: Controller) -> bool:
        if self._remembered_ore_target is None:
            return False

        tx, ty = self._remembered_ore_target
        ore_pos = Position(tx, ty)
        if self._ore_has_completed_extractor(ct, ore_pos):
            self._log(
                ct,
                f"dropping remembered ore {self._remembered_ore_target} (already harvested)",
            )
            self._remembered_ore_target = None
            return False
        blocking_type = self._ore_blocking_structure_type(ct, ore_pos)
        if blocking_type is not None:
            self._log(
                ct,
                (
                    f"dropping remembered ore {self._remembered_ore_target} "
                    f"(blocked by {blocking_type})"
                ),
            )
            self._remembered_ore_target = None
            return False

        self._remembered_ore_nav_target = (tx, ty)
        self._remembered_ore_nav.set_target(tx, ty)
        self._log(ct, f"bridge cycle complete at core, bugnav to remembered ore {(tx, ty)}")
        return True

    def _advance_remembered_ore_navigation(self, ct: Controller) -> bool:
        if self._remembered_ore_nav_target is None:
            return False

        tx, ty = self._remembered_ore_nav_target
        ore_pos = Position(tx, ty)
        my_pos = ct.get_position()
        self._log(ct, f"remembered-ore nav at ({my_pos.x},{my_pos.y}) -> ({tx},{ty})")

        if self._ore_has_completed_extractor(ct, ore_pos):
            self._log(ct, f"remembered ore ({tx},{ty}) already harvested, aborting remembered nav")
            self._remembered_ore_target = None
            self._clear_remembered_ore_navigation()
            return self._run_random_fallback(ct)

        if self._in_action_radius(my_pos, ore_pos):
            self._log(ct, f"remembered ore ({tx},{ty}) in action radius, trying build")
            built = self._build_generator_on_ore(ct, ore_pos)
            if built:
                self._remembered_ore_target = None
                self._clear_remembered_ore_navigation()
                self._clear_primary_ore_target()
                self._start_post_build_alignment(ct, ore_pos)
            else:
                blocking_type = self._ore_blocking_structure_type(ct, ore_pos)
                if blocking_type is not None:
                    self._log(
                        ct,
                        (
                            f"forfeiting remembered ore ({tx},{ty}): "
                            f"blocked by non-road entity {blocking_type}"
                        ),
                    )
                    self._remembered_ore_target = None
                    self._clear_remembered_ore_navigation()
                    return self._run_random_fallback(ct)
                self._log(ct, "generator build on remembered ore not possible this turn")
            return True

        if self._remembered_ore_nav.target != (tx, ty):
            self._remembered_ore_nav.set_target(tx, ty)

        move_dir = self._remembered_ore_nav.next_move(ct)
        if move_dir is None:
            self._log(ct, "remembered-ore TangentBug returned no move this turn")
            return True

        self._log(ct, f"remembered-ore TangentBug move direction={move_dir}")
        self._road_then_move(ct, move_dir)
        return True

    def _start_post_build_alignment(self, ct: Controller, ore_pos: Position) -> None:
        self._post_build_align_ore_target = (ore_pos.x, ore_pos.y)
        self._log(
            ct,
            (
                f"generator placed at ({ore_pos.x},{ore_pos.y}); "
                "aligning to cardinal-adjacent tile before bridge cycle"
            ),
        )
        self._run_post_build_cardinal_alignment(ct)

    def _run_post_build_cardinal_alignment(self, ct: Controller) -> bool:
        if self._post_build_align_ore_target is None:
            return True

        ox, oy = self._post_build_align_ore_target
        ore_pos = Position(ox, oy)
        my_pos = ct.get_position()
        if self._is_adjacent_cardinal(my_pos, ore_pos):
            self._post_build_align_ore_target = None
            self._post_generator_bridge_pending = True
            self._log(
                ct,
                (
                    f"post-build alignment complete at ({my_pos.x},{my_pos.y}); "
                    "entering post-generator bridge cycle"
                ),
            )
            return True

        moved = self._move_to_cardinal_adjacent_tile(ct, ore_pos)
        if moved:
            new_pos = ct.get_position()
            if self._is_adjacent_cardinal(new_pos, ore_pos):
                self._post_build_align_ore_target = None
                self._post_generator_bridge_pending = True
                self._log(
                    ct,
                    (
                        f"post-build alignment moved to ({new_pos.x},{new_pos.y}); "
                        "entering post-generator bridge cycle"
                    ),
                )
            return True

        self._log(ct, f"post-build alignment waiting at ({my_pos.x},{my_pos.y}) for ore ({ox},{oy})")
        return True

    def _move_to_cardinal_adjacent_tile(self, ct: Controller, ore_pos: Position) -> bool:
        my_pos = ct.get_position()
        for move_dir in CARDINAL_DIRECTIONS:
            nxt = my_pos.add(move_dir)
            if not self._is_adjacent_cardinal(nxt, ore_pos):
                continue
            if ct.can_move(move_dir):
                ct.move(move_dir)
                self._log(
                    ct,
                    (
                        f"post-build alignment moved {move_dir} "
                        f"to cardinal-adjacent tile ({nxt.x},{nxt.y})"
                    ),
                )
                return True
        return False

    @staticmethod
    def _is_adjacent_cardinal(a: Position, b: Position) -> bool:
        return abs(a.x - b.x) + abs(a.y - b.y) == 1

    def _finish_bridge_cycle_to_core(self, ct: Controller) -> None:
        self._log(ct, "bridge target is on friendly core tile, exiting bridge cycle")
        self._clear_post_bridge_state()
        self._resume_random_after_bridge = True

    @staticmethod
    def _is_on_friendly_core(ct: Controller, pos: Position) -> bool:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        return (
            ct.get_entity_type(building_id) == EntityType.CORE
            and ct.get_team(building_id) == ct.get_team()
        )

    def _log(self, ct: Controller, message: str) -> None:
        if not self.debug_prints:
            return
        if ct.get_current_round() >= 100:
            return
        pos = ct.get_position()
        print(
            f"[BridgeBuilder][R{ct.get_current_round()}][{pos.x},{pos.y}] {message}",
            file=sys.stderr,
        )

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
    def _run_random_fallback(ct: Controller) -> bool:
        directions = [
            Direction.NORTH,
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
        ]
        random.shuffle(directions)
        for move_dir in directions:
            if ct.can_move(move_dir):
                ct.move(move_dir)
                return True
        return False
