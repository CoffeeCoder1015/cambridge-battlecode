from cambc import Controller, Direction, EntityType, Environment, Position

# Per docs: ACTION_RADIUS_SQ = 2.  A builder can build on any tile where
# dx²+dy² <= 2, i.e. all 8 adjacent neighbours.  It cannot build on the
# tile it is standing on (dist² == 0).
_ACTION_RADIUS_SQ = 2


def _in_action_radius(my_pos: Position, target: Position) -> bool:
    dx = my_pos.x - target.x
    dy = my_pos.y - target.y
    dist_sq = dx * dx + dy * dy
    return 0 < dist_sq <= _ACTION_RADIUS_SQ


class BridgeBuilder:
    def __init__(self):
        self.ore_target: Position | None = None

    def main(self, ct: Controller, known_symmetry: int | None) -> bool:
        """
        Greedy ore-to-generator routine:
        1. If already adjacent to any visible ore -> try to build a generator
           immediately (clearing any friendly blocker first).
        2. Otherwise navigate greedy toward the chosen ore target,
           laying roads before each step.
        3. Stop moving once adjacent; build on the very next turn.
        """
        _ = known_symmetry
        my_pos = ct.get_position()

        # --- Phase 1: instant build if already adjacent to any visible ore ---
        for ore_pos in self._visible_ore_tiles(ct):
            if _in_action_radius(my_pos, ore_pos):
                if self._try_build_generator(ct, ore_pos):
                    self.ore_target = None
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
            return built

        # --- Phase 4: not yet adjacent — move one step closer ---
        return self._step_toward_ore(ct, my_pos)

    # ------------------------------------------------------------------
    # Navigation
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
    # Building
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
