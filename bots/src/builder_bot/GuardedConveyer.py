from cambc import Controller, Direction, EntityType, Environment, Position


class GuardedConveyer:
    """
    State machine for the guarded-conveyor strategy:

      Phase 1 — navigate toward the nearest visible ore tile.
      Phase 2 — build a harvester on the ore; save harvester pos + standing pos.
      Phase 3 — surround the harvester with barriers (one per turn), leaving the
                 saved standing tile open for a future conveyor connection.
    """

    ACTION_RADIUS_SQ = 2
    MOVE_DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
    ORE_ENVS = (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)
    # 8-connected neighbour offsets
    NEIGHBOUR_OFFSETS = [
        (-1, -1), (0, -1), (1, -1),
        (-1,  0),           (1,  0),
        (-1,  1), (0,  1), (1,  1),
    ]

    def __init__(self) -> None:
        self._ore_target: Position | None = None
        self._harvester_pos: Position | None = None
        self._stand_pos: Position | None = None
        self._walls_to_place: list[Position] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, ct: Controller, known_symmetry, symmetry_analyzer) -> bool:
        """Returns True if this mode consumed the turn."""

        # Phase 3: finish surrounding the harvester with barriers
        if self._walls_to_place:
            return self._place_next_wall(ct)

        # Phase 2: adjacent to ore target — build harvester
        if self._ore_target is not None:
            my_pos = ct.get_position()
            if self._dist_sq(my_pos, self._ore_target) <= self.ACTION_RADIUS_SQ:
                return self._try_build_harvester(ct, my_pos)

        # Phase 1: scan and navigate toward nearest ore
        ore_positions = self._get_visible_ore_positions(ct, symmetry_analyzer)
        self._update_target(ct, ore_positions, known_symmetry)

        if self._ore_target is None:
            return False

        return self._navigate_toward(ct, self._ore_target)

    # ------------------------------------------------------------------
    # Phase 2 helpers
    # ------------------------------------------------------------------

    def _try_build_harvester(self, ct: Controller, my_pos: Position) -> bool:
        if not ct.can_build_harvester(self._ore_target):
            return False
        ct.build_harvester(self._ore_target)
        self._harvester_pos = Position(self._ore_target.x, self._ore_target.y)
        self._stand_pos = Position(my_pos.x, my_pos.y)
        self._queue_surrounding_walls()
        self._ore_target = None
        return True

    def _queue_surrounding_walls(self) -> None:
        """Populate wall queue: 8 neighbours of harvester minus the bot's standing tile."""
        hx, hy = self._harvester_pos.x, self._harvester_pos.y
        sx, sy = self._stand_pos.x, self._stand_pos.y
        self._walls_to_place = [
            Position(hx + dx, hy + dy)
            for dx, dy in self.NEIGHBOUR_OFFSETS
            if not (hx + dx == sx and hy + dy == sy)
        ]

    # ------------------------------------------------------------------
    # Phase 3 helpers
    # ------------------------------------------------------------------

    def _place_next_wall(self, ct: Controller) -> bool:
        """
        Work through the wall queue.  For each candidate:
        - Destroy any existing friendly building first (free action).
        - Then place a barrier (costs one action cooldown).
        Skip positions that are out of action range this turn.
        """
        acted = False
        remaining: list[Position] = []

        for pos in self._walls_to_place:
            if acted:
                # Already spent our action this turn — keep rest for later.
                remaining.append(pos)
                continue

            self._clear_tile_if_needed(ct, pos)

            if ct.can_build_barrier(pos):
                ct.build_barrier(pos)
                acted = True
                # tile is done — do NOT re-add to remaining
            else:
                # Out of range or blocked — retry next turn
                remaining.append(pos)

        self._walls_to_place = remaining
        return acted

    def _clear_tile_if_needed(self, ct: Controller, pos: Position) -> None:
        """Destroy any allied building on pos (road, barrier, harvester, etc.) before building."""
        building_id = ct.get_tile_building_id(pos)
        if building_id is not None and ct.can_destroy(pos):
            ct.destroy(pos)

    # ------------------------------------------------------------------
    # Phase 1 helpers
    # ------------------------------------------------------------------

    def _get_visible_ore_positions(self, ct: Controller, symmetry_analyzer) -> list[Position]:
        ores: dict[tuple[int, int], Position] = {}

        # Leverage stored scan memory from symmetry analyzer.
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
        # Invalidate stale target (e.g. harvester already placed by another bot).
        if self._ore_target is not None:
            still_ore = any(
                p.x == self._ore_target.x and p.y == self._ore_target.y
                for p in ore_positions
            )
            if not still_ore:
                self._ore_target = None

        if self._ore_target is not None:
            return

        my_pos = ct.get_position()
        candidates = [
            ore for ore in ore_positions
            if self._dist_sq(my_pos, ore) > self.ACTION_RADIUS_SQ
        ]
        if not candidates:
            return

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

    def _navigate_toward(self, ct: Controller, target: Position) -> bool:
        my_pos = ct.get_position()
        best_dir = self._get_greedy_step(ct, my_pos, target)
        if best_dir is None:
            return False

        ahead = my_pos.add(best_dir)
        if not self._has_friendly_road(ct, ahead):
            if ct.can_build_road(ahead):
                ct.build_road(ahead)
                if ct.can_move(best_dir):
                    ct.move(best_dir)
                return True

        if ct.can_move(best_dir):
            ct.move(best_dir)
            return True

        return False

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

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    def _has_friendly_road(self, ct: Controller, pos: Position) -> bool:
        building_id = ct.get_tile_building_id(pos)
        if building_id is None:
            return False
        return (
            ct.get_entity_type(building_id) == EntityType.ROAD
            and ct.get_team(building_id) == ct.get_team()
        )

    @staticmethod
    def _dist_sq(a: Position, b: Position) -> int:
        return (a.x - b.x) ** 2 + (a.y - b.y) ** 2
