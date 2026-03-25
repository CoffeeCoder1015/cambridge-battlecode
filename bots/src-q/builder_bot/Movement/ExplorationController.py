import random
import math
from cambc import Controller, Direction, EntityType, Environment, Position

DIR_VECTORS: dict[Direction, tuple[int, int]] = {
    Direction.NORTH: (0, -1),
    Direction.NORTHEAST: (1, -1),
    Direction.EAST: (1, 0),
    Direction.SOUTHEAST: (1, 1),
    Direction.SOUTH: (0, 1),
    Direction.SOUTHWEST: (-1, 1),
    Direction.WEST: (-1, 0),
    Direction.NORTHWEST: (-1, -1),
}

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


def dir_dot(a: Direction, b: Direction) -> int:
    if a not in DIR_VECTORS or b not in DIR_VECTORS:
        return 0
    ax, ay = DIR_VECTORS[a]
    bx, by = DIR_VECTORS[b]
    return ax * bx + ay * by


def is_backward(d: Direction, spawn_direction: Direction) -> bool:
    return dir_dot(d, spawn_direction) <= 0


def gaussian(x: float, variance: float) -> float:
    if variance <= 0:
        return 1.0 if x == 2 else 0.0
    return math.exp(-((x - 2) ** 2) / (2 * variance))


def vec_to_dir(dx: int, dy: int) -> Direction:
    dx = max(-1, min(1, dx))
    dy = max(-1, min(1, dy))
    if dx == 0 and dy == 0:
        return Direction.NORTH
    for d, vec in DIR_VECTORS.items():
        if vec == (dx, dy):
            return d
    return Direction.NORTH


class ExplorationController:
    def __init__(
        self,
        spawn_direction: Direction,
        map_width: int,
        map_height: int,
    ):
        self.spawn_direction = spawn_direction
        self.heading = spawn_direction
        self.map_width = map_width
        self.map_height = map_height

        self.steps_on_heading = 0
        self.prev_pos: Position | None = None
        self.stuck_counter = 0
        self.steps_since_resample = 0
        self.local_coverage = 0.0

        self.current_quadrant: tuple[int, int] | None = None
        self.ticks_in_quadrant = 0

        self._resample_heading(None)

    def _resample_heading(self, ct: Controller | None) -> None:
        if ct is not None:
            buildings = ct.get_nearby_buildings()
            my_team = ct.get_team()
            ally_development = sum(
                1
                for b in buildings
                if ct.get_team(b) == my_team
                and ct.get_entity_type(b) in (
                    EntityType.ROAD,
                    EntityType.BRIDGE,
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                )
            )

            vision_tiles = len(ct.get_nearby_tiles())
            self.local_coverage = ally_development / max(1.0, float(vision_tiles))
            coverage = self.local_coverage
            max_variance = 2.0
            density_scale = max_variance * max(0.01, (1.0 - coverage * 4.0))

            min_interval = 2
            base_interval = 12
            interval_scale = 5.0
            self.steps_since_resample = max(
                min_interval, base_interval - int(density_scale * interval_scale)
            )
        else:
            density_scale = 1.0

        valid_directions = [
            d for d in DIRECTIONS if not is_backward(d, self.spawn_direction)
        ]
        weights = [
            gaussian(dir_dot(d, self.spawn_direction), variance=density_scale)
            for d in valid_directions
        ]

        if sum(weights) == 0:
            self.heading = self.spawn_direction
        else:
            self.heading = random.choices(valid_directions, weights=weights)[0]

    def get_orthogonal_step(self) -> Direction:
        dx, dy = DIR_VECTORS[self.spawn_direction]
        choices = []
        if dx > 0:
            choices.append(Direction.EAST)
        elif dx < 0:
            choices.append(Direction.WEST)
        if dy > 0:
            choices.append(Direction.SOUTH)
        elif dy < 0:
            choices.append(Direction.NORTH)

        if len(choices) == 1:
            return choices[0]
        else:
            return choices[self.steps_on_heading % 2]

    def step(self, ct: Controller) -> bool:
        my_pos = ct.get_position()

        self._update_quadrant(ct, my_pos)

        if self._handle_stuck(ct, my_pos):
            return True

        step_dir = self._compute_step_direction(ct, my_pos)

        valid_candidates = self._filter_valid_directions(ct, my_pos, step_dir)

        candidate = self._pick_best_candidate(ct, my_pos, valid_candidates, step_dir)

        return self._execute_movement(ct, my_pos, candidate)

    def _update_quadrant(self, ct: Controller, my_pos: Position) -> None:
        cx = max(1, self.map_width // 2)
        cy = max(1, self.map_height // 2)
        qx = 0 if my_pos.x < cx else 1
        qy = 0 if my_pos.y < cy else 1
        quadrant = (qx, qy)

        if self.current_quadrant is None:
            self.current_quadrant = quadrant
        elif self.current_quadrant == quadrant:
            if ct.get_move_cooldown() == 0 and ct.get_action_cooldown() == 0:
                self.ticks_in_quadrant += 1
                if self.ticks_in_quadrant > 150:
                    import sys
                    candidates = [(0, 0), (0, 1), (1, 0), (1, 1)]
                    candidates.remove(quadrant)
                    new_q = random.choice(candidates)
                    target_x = new_q[0] * cx + cx // 2
                    target_y = new_q[1] * cy + cy // 2
                    target_pos = Position(int(target_x), int(target_y))
                    new_dir = my_pos.direction_to(target_pos)
                    if new_dir != Direction.CENTRE:
                        print(f"[{ct.get_id()}] Context Aware: Leaping from {quadrant} to {new_q}. Dir: {new_dir.name}", file=sys.stderr)
                        self.spawn_direction = new_dir
                        self.current_quadrant = new_q
                        self.ticks_in_quadrant = 0
                        self._resample_heading(ct)
        else:
            self.current_quadrant = quadrant
            self.ticks_in_quadrant = 0

    def _handle_stuck(self, ct: Controller, my_pos: Position) -> bool:
        if self.prev_pos is not None and self.prev_pos == my_pos:
            if ct.get_move_cooldown() == 0 and ct.get_action_cooldown() == 0:
                self.stuck_counter += 1
                if self.stuck_counter >= 5:
                    import sys
                    valid_bounce_dirs = []
                    for d in DIRECTIONS:
                        if (
                            dir_dot(d, self.spawn_direction) <= 0
                            and d != self.spawn_direction.opposite()
                        ):
                            valid_bounce_dirs.append(d)

                    if valid_bounce_dirs:
                        new_dir = random.choice(valid_bounce_dirs)
                    else:
                        new_dir = self._reflect_direction(
                            self.spawn_direction, ct, my_pos
                        )

                    print(f"[{ct.get_id()}] BOUNCE: {self.spawn_direction.name} -> {new_dir.name}", file=sys.stderr)
                    self.spawn_direction = new_dir
                    self.stuck_counter = 0
                    self._resample_heading(ct)
                    return True
                elif self.stuck_counter >= 3:
                    self.steps_on_heading += 1
                    self._resample_heading(ct)
                    return True
        else:
            self.stuck_counter = 0

        self.prev_pos = my_pos
        return False

    def _reflect_direction(
        self, heading: Direction, ct: Controller, my_pos: Position
    ) -> Direction:
        hx, hy = DIR_VECTORS[heading]

        def is_static_block(pos: Position) -> bool:
            try:
                if not ct.is_in_vision(pos):
                    return True
                env = ct.get_tile_env(pos)
                if env in (
                    Environment.WALL,
                    Environment.ORE_TITANIUM,
                    Environment.ORE_AXIONITE,
                ):
                    return True
                
                # Use is_tile_passable for a more robust check that accounts for roads/bridges
                if not ct.is_tile_passable(pos):
                    return True
            except Exception:
                return True
            return False

        x_blocked = False
        y_blocked = False

        if hx != 0:
            if is_static_block(my_pos.add(vec_to_dir(hx, 0))):
                x_blocked = True

        if hy != 0:
            if is_static_block(my_pos.add(vec_to_dir(0, hy))):
                y_blocked = True

        if not x_blocked and not y_blocked:
            if is_static_block(my_pos.add(heading)):
                x_blocked = True
                y_blocked = True

        rx = -hx if x_blocked else hx
        ry = -hy if y_blocked else hy

        if rx == hx and ry == hy:
            rx, ry = -hx, -hy

        return vec_to_dir(rx, ry)

    def _compute_step_direction(self, ct: Controller, my_pos: Position) -> Direction:
        if (
            self.heading != self.spawn_direction
            and dir_dot(self.heading, self.spawn_direction) != 2
        ):
            dx, dy = DIR_VECTORS[self.heading]
            choices = []
            if dx > 0:
                choices.append(Direction.EAST)
            elif dx < 0:
                choices.append(Direction.WEST)
            if dy > 0:
                choices.append(Direction.SOUTH)
            elif dy < 0:
                choices.append(Direction.NORTH)

            if len(choices) > 0:
                return choices[self.steps_on_heading % len(choices)]

        return self.get_orthogonal_step()

    def _filter_valid_directions(
        self, ct: Controller, my_pos: Position, step_dir: Direction
    ) -> list[Direction]:
        valid_candidates = []
        c = step_dir

        for _ in range(7):
            target_pos = my_pos.add(c)

            if (
                target_pos.x < 0
                or target_pos.x >= self.map_width
                or target_pos.y < 0
                or target_pos.y >= self.map_height
            ):
                c = c.rotate_right()
                continue

            if is_backward(c, self.spawn_direction):
                c = c.rotate_right()
                continue

            try:
                env = ct.get_tile_env(target_pos)
                if env != Environment.EMPTY:
                    c = c.rotate_right()
                    continue
            except Exception:
                c = c.rotate_right()
                continue

            try:
                occ_id = ct.get_tile_building_id(target_pos)
                if occ_id is not None:
                    occ_type = ct.get_entity_type(occ_id)
                    occ_team = ct.get_team(occ_id)
                    is_traversable_enemy = occ_team != ct.get_team() and occ_type in (
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                        EntityType.ROAD,
                        EntityType.BRIDGE,
                    )

                    if not is_traversable_enemy:
                        if occ_type in (
                            EntityType.GUNNER,
                            EntityType.SENTINEL,
                            EntityType.BREACH,
                            EntityType.HARVESTER,
                            EntityType.FOUNDRY,
                            EntityType.CORE,
                            EntityType.LAUNCHER,
                        ):
                            c = c.rotate_right()
                            continue
            except Exception:
                pass

            if not ct.is_tile_passable(target_pos):
                if ct.get_action_cooldown() == 0:
                    if not ct.can_build_road(target_pos):
                        c = c.rotate_right()
                        continue

            valid_candidates.append(c)
            c = c.rotate_right()

        return valid_candidates

    def _pick_best_candidate(
        self,
        ct: Controller,
        my_pos: Position,
        valid_candidates: list[Direction],
        fallback_dir: Direction,
    ) -> Direction:
        if not valid_candidates:
            return fallback_dir

        my_team = ct.get_team()
        for cand in valid_candidates:
            t_pos = my_pos.add(cand)
            try:
                b_id = ct.get_tile_building_id(t_pos)
                if b_id is not None and ct.get_team(b_id) == my_team:
                    b_type = ct.get_entity_type(b_id)
                    if b_type in (EntityType.ROAD, EntityType.BRIDGE, EntityType.CONVEYOR):
                        return cand
            except Exception:
                pass

        return valid_candidates[0]

    def _execute_movement(
        self, ct: Controller, my_pos: Position, candidate: Direction
    ) -> bool:
        target_pos = my_pos.add(candidate)

        if not ct.is_tile_passable(target_pos):
            if ct.get_action_cooldown() == 0:
                titanium = ct.get_global_resources()[0]
                if titanium >= 1:
                    if ct.can_build_road(target_pos):
                        ct.build_road(target_pos)
                        return True

        if ct.get_move_cooldown() == 0:
            if ct.can_move(candidate):
                ct.move(candidate)
                self.stuck_counter = 0
                self.steps_on_heading += 1
                self.steps_since_resample -= 1

                if self.steps_since_resample <= 0:
                    self._resample_heading(ct)

                new_pos = ct.get_position()
                if my_pos != new_pos:
                    if ct.get_action_cooldown() == 0:
                        titanium = ct.get_global_resources()[0]
                        if titanium >= 1:
                            if ct.can_build_road(my_pos):
                                ct.build_road(my_pos)

                return True

        return False
