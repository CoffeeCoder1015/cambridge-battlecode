import sys

from cambc import Controller, EntityType, Position, Environment, Direction


DIRECTIONS = [
    Direction.NORTH,
    Direction.SOUTH,
    Direction.EAST,
    Direction.WEST,
    Direction.NORTHEAST,
    Direction.NORTHWEST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
]


# Build turret on the tile next to the harvester
CARDINAL_DIRECTIONS = [
    Direction.NORTH,
    Direction.SOUTH,
    Direction.EAST,
    Direction.WEST,
]


class Hound:
    def __init__(self, debug_prints: bool = False):
        self.debug_prints = debug_prints

    PRIORITY_MAP = {
        EntityType.BRIDGE: 70,
        EntityType.CONVEYOR: 60,
        EntityType.ROAD: 50,
    }

    COLOR_MAP = {
        EntityType.BRIDGE: (255, 0, 0),
        EntityType.CONVEYOR: (255, 160, 0),
        EntityType.ROAD: (255, 255, 0),
    }

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
        # Priority 1: Attack or approach nearby enemy buildings
        attack_acted = self.attack(
            ct, set_nav_target, execute_nav_step, enemy_core_target
        )
        if attack_acted:
            return True, enemy_core_target

        if enemy_core_target is None:
            hound_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)
            if hound_target is None:
                return False, enemy_core_target
            enemy_core_target = hound_target
        

        set_nav_target(*enemy_core_target)
        return execute_nav_step(ct), enemy_core_target

    def attack(
        self, ct: Controller, set_nav_target, execute_nav_step, enemy_core_target
    ):
        if enemy_core_target is not None:
            core_position = Position(*enemy_core_target)
            current_position = ct.get_position()
            core_dir = current_position.direction_to(core_position)
            core_position.add(core_dir.opposite())
            dist = current_position.distance_squared(core_position)
            if dist <= 32:
                ct.draw_indicator_line(current_position,core_position,0,255,0)
            elif dist <= 64:
                ct.draw_indicator_line(current_position,core_position,255,255,0)
            else:
                ct.draw_indicator_line(current_position,core_position,255,0,0)

        nearby_buildings = ct.get_nearby_buildings()
        current_position = ct.get_position()
        nearby_enemy_buildings = [
            (
                ct.get_entity_type(b),
                current_position.distance_squared(ct.get_position(b)),
                b,
            )
            for b in nearby_buildings
            if ct.get_team(b) != ct.get_team()
        ]
        nearby_enemy_buildings.sort(key=lambda x: x[1])

        for target_type, _, target_id in nearby_enemy_buildings:
            if target_type != EntityType.CORE and target_type != EntityType.HARVESTER:
                # Attack non-harvester/non-core buildings normally
                return self.attack_sqr(ct, set_nav_target, execute_nav_step, target_id)
        return False


    def build_turret(
        self,
        ct: Controller,
        set_nav_target,
        execute_nav_step,
        harvester_id,
        enemy_core_target,
    ):
        harvester_pos = ct.get_position(harvester_id)

        for direction in CARDINAL_DIRECTIONS:
            turret_pos = harvester_pos.add(direction)
            build_direction = direction
            if enemy_core_target is not None:
                core_pos = Position(enemy_core_target[0], enemy_core_target[1])
                build_direction = turret_pos.direction_to(core_pos)

                # AMMO BLOCKAGE: Don't point directly into the harvester
                opposite_direction = self.get_opposite_direction(direction)
                if build_direction == opposite_direction:
                    build_direction = self.get_diagonal_adjustment(
                        turret_pos, core_pos, opposite_direction
                    )

            if ct.can_build_sentinel(turret_pos, build_direction):
                ct.build_sentinel(turret_pos, build_direction)
                return True

        # Too far away
        # move towards harvester

        ct.draw_indicator_line(ct.get_position(), harvester_pos, 255, 255, 0)
        set_nav_target(harvester_pos.x, harvester_pos.y)
        # Return True as we have decided on a target and acted (moving)
        return execute_nav_step(ct)

    def attack_sqr(
        self,
        ct: Controller,
        set_nav_target,
        execute_nav_step,
        target_id,
    ) -> bool:
        b_pos = ct.get_position(target_id)
        my_pos = ct.get_position()
        etype = ct.get_entity_type(target_id)

        # Highlight target using the requested color map
        dot_color = self.COLOR_MAP.get(etype, (255, 160, 0))  # Default: Orange
        ct.draw_indicator_dot(b_pos, *dot_color)

        # Physically walk onto the tile if not already there
        if my_pos.x != b_pos.x or my_pos.y != b_pos.y:
            straight_dir = my_pos.direction_to(b_pos)
            post_move_pos = my_pos.add(straight_dir)
            if ct.can_move(straight_dir) and post_move_pos == b_pos:
                ct.move(straight_dir)
                if ct.can_fire(b_pos):
                    ct.fire(b_pos)
                    return True

            set_nav_target(b_pos.x, b_pos.y)
            if execute_nav_step(ct):
                # Re-check if we reached the tile after moving to fire immediately
                my_pos = ct.get_position()
                if my_pos.x == b_pos.x and my_pos.y == b_pos.y:
                    if ct.can_fire(b_pos):
                        ct.fire(b_pos)
                return True
        else:
            # We are on the enemy tile, open fire
            if ct.can_fire(b_pos):
                ct.fire(b_pos)
                return True
        return False

    def get_opposite_direction(self, direction: Direction) -> Direction:
        mapping = {
            Direction.NORTH: Direction.SOUTH,
            Direction.SOUTH: Direction.NORTH,
            Direction.EAST: Direction.WEST,
            Direction.WEST: Direction.EAST,
        }
        return mapping.get(direction, direction)

    def get_diagonal_adjustment(
        self, turret_pos: Position, core_pos: Position, blocked_dir: Direction
    ) -> Direction:
        # blocked_dir is the cardinal direction pointing to the harvester.
        # We pick a diagonal adjacent to blocked_dir that points towards the core.
        dx = core_pos.x - turret_pos.x
        dy = core_pos.y - turret_pos.y

        if blocked_dir == Direction.NORTH:  # Harvester is North
            return Direction.NORTHWEST if dx < 0 else Direction.NORTHEAST
        if blocked_dir == Direction.SOUTH:  # Harvester is South
            return Direction.SOUTHWEST if dx < 0 else Direction.SOUTHEAST
        if blocked_dir == Direction.EAST:  # Harvester is East
            return Direction.NORTHEAST if dy < 0 else Direction.SOUTHEAST
        if blocked_dir == Direction.WEST:  # Harvester is West
            return Direction.NORTHWEST if dy < 0 else Direction.SOUTHWEST
        return blocked_dir
