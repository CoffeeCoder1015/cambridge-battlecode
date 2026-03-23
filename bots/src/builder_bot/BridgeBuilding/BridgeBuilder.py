from cambc import Controller, Direction, EntityType, Environment, Position

from ..Movement.TangentBug import TangentBug

# Per docs: ACTION_RADIUS_SQ = 2.  A builder can build on any tile where
# dx²+dy² <= 2, i.e. all 8 adjacent neighbours.  It cannot build on the
# tile it is standing on (dist² == 0).
_ACTION_RADIUS_SQ = 2
_BRIDGE_RADIUS_SQ = 9  # BRIDGE_TARGET_RADIUS_SQ from docs


def _in_action_radius(my_pos: Position, target: Position) -> bool:
    dx = my_pos.x - target.x
    dy = my_pos.y - target.y
    dist_sq = dx * dx + dy * dy
    return 0 < dist_sq <= _ACTION_RADIUS_SQ


def _dist_sq(a: Position, b: Position) -> int:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2


class BridgeBuilder:
    def __init__(self):
        self.ore_target: Position | None = None

        # Bridge-back-to-core state
        self._back_active: bool = False
        # Phases: "CLEAR_AND_PICK", "BRIDGE_AND_MOVE", "FINAL_BRIDGE"
        self._back_phase: str = "CLEAR_AND_PICK"
        self._back_target: Position | None = None
        self._back_bridge_built: bool = False
        self._back_nav: TangentBug = TangentBug()

    def main(
        self,
        ct: Controller,
        known_symmetry: int | None,
        core_pos: tuple[int, int] | None = None,
    ) -> bool:
        """
        Greedy ore-to-generator routine, followed by bridge-back-to-core:
        1. If already adjacent to any visible ore -> try to build a generator
           immediately (clearing any friendly blocker first).
        2. Otherwise navigate greedy toward the chosen ore target,
           laying roads before each step.
        3. Stop moving once adjacent; build on the very next turn.
        4. After the generator is placed, enter bridge-back loop:
           a. Clear underfoot + pick best target within bridge radius toward core.
           b. Build bridge at feet (my_pos → target), then bugnav to target.
           c. Repeat until target == core; then place final bridge and exit.
        """
        _ = known_symmetry

        # If bridge-back mode is active, hand control to that loop exclusively.
        if self._back_active:
            return self._run_bridge_back(ct, core_pos)

        my_pos = ct.get_position()

        # --- Phase 1: instant build if already adjacent to any visible ore ---
        for ore_pos in self._visible_ore_tiles(ct):
            if _in_action_radius(my_pos, ore_pos):
                if self._try_build_generator(ct, ore_pos):
                    self.ore_target = None
                    self._enter_bridge_back()
                    return True

        # --- Phase 2: pick a target if we do not have one ---
        if self.ore_target is None:
            candidate = self._select_nearest_ore(ct, my_pos, max_steps=8)
            if candidate is None:
                return False
            self.ore_target = candidate

        # --- Phase 3: if adjacent to target, attempt build (may need several
        #     turns to clear action cooldown / friendly blockers) ---
        if _in_action_radius(my_pos, self.ore_target):
            built = self._try_build_generator(ct, self.ore_target)
            if built:
                self.ore_target = None
                self._enter_bridge_back()
            return built

        # --- Phase 4: not yet adjacent — move one step closer ---
        return self._step_toward_ore(ct, my_pos)

    # ------------------------------------------------------------------
    # Bridge-back-to-core logic
    # ------------------------------------------------------------------

    def _enter_bridge_back(self) -> None:
        self._back_active = True
        self._back_phase = "CLEAR_AND_PICK"
        self._back_target = None
        self._back_bridge_built = False

    def _run_bridge_back(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
    ) -> bool:
        if core_pos is None:
            # Wait until we know where the core is.
            return True

        core = Position(core_pos[0], core_pos[1])

        if self._back_phase == "CLEAR_AND_PICK":
            return self._do_clear_and_pick(ct, core)
        if self._back_phase == "BRIDGE_AND_MOVE":
            return self._do_bridge_and_move(ct, core)
        if self._back_phase == "FINAL_BRIDGE":
            return self._do_final_bridge(ct, core)

        return True

    def _do_clear_and_pick(self, ct: Controller, core: Position) -> bool:
        my_pos = ct.get_position()
        rnd = ct.get_current_round()

        # Destroy anything underfoot (destroy has no action-cooldown cost).
        building_id = ct.get_tile_building_id(my_pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            b_team = ct.get_team(building_id)
            if b_type != EntityType.CORE and b_team == ct.get_team() and ct.can_destroy(my_pos):
                ct.destroy(my_pos)
                if rnd < 100:
                    print(
                        f"[R{rnd}] BridgeBack CLEAR_AND_PICK: destroyed {b_type} at {my_pos}"
                    )

        # Pick target: best bridge-range tile toward core, not blocked by wall/generator.
        target = self._pick_bridge_target(ct, my_pos, core)
        if target is None:
            if rnd < 100:
                print(
                    f"[R{rnd}] BridgeBack CLEAR_AND_PICK: no valid target found "
                    f"(my_pos={my_pos}, core={core})"
                )
            return True  # Stay in bridge-back mode; suppress other code.

        self._back_target = target
        self._back_bridge_built = False

        if (target.x, target.y) == (core.x, core.y):
            self._back_phase = "FINAL_BRIDGE"
            if rnd < 100:
                print(
                    f"[R{rnd}] BridgeBack CLEAR_AND_PICK: target is core {core} "
                    f"→ entering FINAL_BRIDGE"
                )
        else:
            self._back_phase = "BRIDGE_AND_MOVE"
            self._back_nav.set_target(target.x, target.y)
            if rnd < 100:
                print(
                    f"[R{rnd}] BridgeBack CLEAR_AND_PICK: picked target={target}, "
                    f"core={core} → entering BRIDGE_AND_MOVE"
                )

        return True

    def _do_bridge_and_move(self, ct: Controller, core: Position) -> bool:
        _ = core
        if self._back_target is None:
            self._back_phase = "CLEAR_AND_PICK"
            return True

        target = self._back_target
        my_pos = ct.get_position()
        rnd = ct.get_current_round()

        # Build bridge at my_pos → target (once per leg, when action cooldown is clear).
        if not self._back_bridge_built:
            # Clear underfoot first if anything is blocking the bridge placement.
            building_id = ct.get_tile_building_id(my_pos)
            if building_id is not None:
                b_type = ct.get_entity_type(building_id)
                b_team = ct.get_team(building_id)
                if b_type != EntityType.CORE and b_team == ct.get_team() and ct.can_destroy(my_pos):
                    ct.destroy(my_pos)
                    if rnd < 100:
                        print(
                            f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: cleared {b_type} at {my_pos}"
                        )
                    # Move on this turn as well (fall through to nav step below).

            if ct.get_action_cooldown() == 0:
                if ct.can_build_bridge(my_pos, target):
                    ct.build_bridge(my_pos, target)
                    self._back_bridge_built = True
                    if rnd < 100:
                        print(
                            f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: built bridge "
                            f"{my_pos} → {target}"
                        )
                else:
                    if rnd < 100:
                        print(
                            f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: cannot build bridge "
                            f"{my_pos} → {target}, cd={ct.get_action_cooldown()}"
                        )

        # Navigate toward target using bugnav.
        move_dir = self._back_nav.next_move(ct)
        if move_dir is not None:
            if ct.can_move(move_dir):
                ct.move(move_dir)
                new_pos = ct.get_position()
                if rnd < 100:
                    print(
                        f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: moved {move_dir} "
                        f"→ {new_pos} (target={target})"
                    )
                if (new_pos.x, new_pos.y) == (target.x, target.y):
                    self._back_phase = "CLEAR_AND_PICK"
                    self._back_target = None
                    if rnd < 100:
                        print(
                            f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: arrived at {target} "
                            f"→ back to CLEAR_AND_PICK"
                        )
            else:
                if rnd < 100:
                    print(
                        f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: cannot move {move_dir} "
                        f"(target={target})"
                    )
        else:
            # nav returned None → already at target or unreachable.
            if (my_pos.x, my_pos.y) == (target.x, target.y):
                self._back_phase = "CLEAR_AND_PICK"
                self._back_target = None
                if rnd < 100:
                    print(
                        f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: nav=None, already at "
                        f"{target} → back to CLEAR_AND_PICK"
                    )
            else:
                if rnd < 100:
                    print(
                        f"[R{rnd}] BridgeBack BRIDGE_AND_MOVE: nav=None but not at "
                        f"target {target}, my_pos={my_pos}"
                    )

        return True  # Always own the turn while bridge-back is active.

    def _do_final_bridge(self, ct: Controller, core: Position) -> bool:
        if self._back_target is None:
            self._back_active = False
            return True

        target = self._back_target
        my_pos = ct.get_position()
        rnd = ct.get_current_round()

        # Clear underfoot so the bridge can be placed.
        building_id = ct.get_tile_building_id(my_pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            b_team = ct.get_team(building_id)
            if b_type != EntityType.CORE and b_team == ct.get_team() and ct.can_destroy(my_pos):
                ct.destroy(my_pos)
                if rnd < 100:
                    print(
                        f"[R{rnd}] BridgeBack FINAL_BRIDGE: cleared {b_type} at {my_pos}"
                    )
                return True

        if ct.get_action_cooldown() == 0:
            if ct.can_build_bridge(my_pos, target):
                ct.build_bridge(my_pos, target)
                self._back_active = False
                if rnd < 100:
                    print(
                        f"[R{rnd}] BridgeBack FINAL_BRIDGE: built bridge "
                        f"{my_pos} → {target} (core). Bridge-back COMPLETE!"
                    )
                return True
            if rnd < 100:
                print(
                    f"[R{rnd}] BridgeBack FINAL_BRIDGE: cannot build bridge "
                    f"{my_pos} → {target} (core={core})"
                )
        else:
            if rnd < 100:
                print(
                    f"[R{rnd}] BridgeBack FINAL_BRIDGE: waiting, cd={ct.get_action_cooldown()}"
                )

        return True  # Own the turn while waiting.

    # ------------------------------------------------------------------
    # Bridge target selection
    # ------------------------------------------------------------------

    def _pick_bridge_target(
        self,
        ct: Controller,
        my_pos: Position,
        core: Position,
    ) -> Position | None:
        """
        Find the best tile within bridge radius (dist² <= 9) toward core.
        Candidates are sorted by:
          1. Closest to core (primary — we want the most progress).
          2. Furthest from my_pos within bridge radius (secondary — use max range).
        Tiles blocked by a wall or generator/harvester are skipped.
        """
        w = ct.get_map_width()
        h = ct.get_map_height()

        candidates: list[tuple[int, int, Position]] = []
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx == 0 and dy == 0:
                    continue
                bridge_dist_sq = dx * dx + dy * dy
                if bridge_dist_sq > _BRIDGE_RADIUS_SQ:
                    continue
                x = my_pos.x + dx
                y = my_pos.y + dy
                if not (0 <= x < w and 0 <= y < h):
                    continue
                candidate = Position(x, y)
                if self._is_bridge_target_blocked(ct, candidate):
                    continue
                dist_to_core = _dist_sq(candidate, core)
                # Sort key: (dist_to_core ASC, bridge_dist_sq DESC)
                candidates.append((dist_to_core, -bridge_dist_sq, candidate))

        if not candidates:
            return None

        candidates.sort(key=lambda t: (t[0], t[1]))
        return candidates[0][2]

    def _is_bridge_target_blocked(self, ct: Controller, pos: Position) -> bool:
        """Return True if the tile is a wall or has a generator/harvester on it."""
        try:
            env = ct.get_tile_env(pos)
        except Exception:
            return True
        if env == Environment.WALL:
            return True

        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False

        b_type = ct.get_entity_type(building_id)
        # Harvesters (generators) block; enemy buildings also block.
        if b_type == EntityType.HARVESTER:
            return True
        if ct.get_team(building_id) != ct.get_team():
            return True

        return False

    # ------------------------------------------------------------------
    # Navigation (ore phase)
    # ------------------------------------------------------------------

    def _step_toward_ore(self, ct: Controller, my_pos: Position) -> bool:
        if self.ore_target is None:
            return False

        move_dir = my_pos.direction_to(self.ore_target)
        if move_dir == Direction.CENTRE:
            # direction_to returned CENTRE but we are not adjacent — stuck.
            self.ore_target = None
            return False

        move_pos = my_pos.add(move_dir)
        acted = False

        # Lay a road on the destination tile before stepping onto it.
        has_friendly_marker = self._has_friendly_marker_at(ct, move_pos)
        if ct.can_build_road(move_pos) and not has_friendly_marker:
            ct.build_road(move_pos)
            acted = True

        if ct.can_move(move_dir):
            ct.move(move_dir)
            return True

        if acted:
            return True

        # Cannot move and nothing else done — replan next round.
        self.ore_target = None
        return False

    # ------------------------------------------------------------------
    # Building (ore phase)
    # ------------------------------------------------------------------

    def _try_build_generator(self, ct: Controller, target: Position) -> bool:
        """
        Clear any friendly blocker on the ore tile then attempt to build.
        Must be called when standing adjacent (dist² <= ACTION_RADIUS_SQ).
        """
        # Clear obstructions first; destroy does NOT cost action cooldown.
        self._clear_generator_obstructions(ct, target)

        if ct.get_action_cooldown() != 0:
            return False

        # Prefer harvester (the primary ore-building action).
        if ct.can_build_harvester(target):
            ct.build_harvester(target)
            return True

        # Fall back to generator if the API is available.
        can_build_generator = getattr(ct, "can_build_generator", None)
        build_generator = getattr(ct, "build_generator", None)
        if callable(can_build_generator) and callable(build_generator):
            if can_build_generator(target):
                build_generator(target)
                return True

        return False

    def _clear_generator_obstructions(self, ct: Controller, target: Position) -> bool:
        """
        Remove friendly roads, markers, or walls on the ore tile.
        `destroy` has no action-cooldown cost so this is safe to call every turn.
        """
        acted = False

        building_id = ct.get_tile_building_id(target)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            b_team = ct.get_team(building_id)
            if b_team == ct.get_team() and b_type == EntityType.ROAD:
                if ct.can_destroy(target):
                    ct.destroy(target)
                    acted = True

        marker_id = self._find_marker_at(ct, target)
        if marker_id is not None:
            if ct.can_destroy(target):
                ct.destroy(target)
                acted = True

        try:
            env = ct.get_tile_env(target)
        except Exception:
            env = None
        if env == Environment.WALL and ct.can_destroy(target):
            ct.destroy(target)
            acted = True

        return acted

    # ------------------------------------------------------------------
    # Tile scan helpers
    # ------------------------------------------------------------------

    def _visible_ore_tiles(self, ct: Controller) -> list[Position]:
        ores: list[Position] = []
        for tile in ct.get_nearby_tiles():
            try:
                env = ct.get_tile_env(tile)
            except Exception:
                continue
            if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                ores.append(tile)
        return ores

    def _select_nearest_ore(
        self,
        ct: Controller,
        origin: Position,
        max_steps: int,
    ) -> Position | None:
        best_tile: Position | None = None
        best_dist: int | None = None

        for tile in ct.get_nearby_tiles():
            try:
                env = ct.get_tile_env(tile)
            except Exception:
                continue
            if env not in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                continue
            steps = max(abs(tile.x - origin.x), abs(tile.y - origin.y))
            if steps > max_steps:
                continue
            if best_dist is None or steps < best_dist:
                best_tile = tile
                best_dist = steps

        return best_tile

    # ------------------------------------------------------------------
    # Marker helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_marker_at(ct: Controller, pos: Position) -> int | None:
        for entity_id in ct.get_nearby_entities():
            if ct.get_entity_type(entity_id) != EntityType.MARKER:
                continue
            if ct.get_position(entity_id) == pos:
                return entity_id
        return None

    @staticmethod
    def _has_friendly_marker_at(ct: Controller, pos: Position) -> bool:
        marker_id = BridgeBuilder._find_marker_at(ct, pos)
        if marker_id is None:
            return False
        return ct.get_team(marker_id) == ct.get_team()
