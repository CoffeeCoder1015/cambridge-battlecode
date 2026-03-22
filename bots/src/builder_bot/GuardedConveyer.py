from cambc import Controller, Direction, EntityType, Environment, Position


class GuardedConveyer:
    """Greedy ore approach logic for guarded-conveyor mode."""

    ACTION_RADIUS_SQ = 2
    MOVE_DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
    ORE_ENVS = (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)

    def __init__(self) -> None:
        self._ore_target: Position | None = None

    def run(self, ct: Controller, known_symmetry, symmetry_analyzer) -> bool:
        """
        Returns True if this mode consumed the turn with a road build or move.
        """
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

    @staticmethod
    def _dist_sq(a: Position, b: Position) -> int:
        return (a.x - b.x) ** 2 + (a.y - b.y) ** 2
