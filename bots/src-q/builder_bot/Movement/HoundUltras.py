import sys
from collections import deque

from cambc import Controller, EntityType, Position, Direction


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
        self.tita_source_cache = {}
        self.offensive_target_pos: tuple[int, int] | None = None
        self.offensive_no_go: dict[
            tuple[int, int], int
        ] = {}  # position -> round validated
        self.titanium_history = deque(maxlen=10)
        self.last_titanium = None

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
        print("I AM HOUND")

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
        if enemy_core_target is None:
            hound_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)
            if hound_target is not None:
                enemy_core_target = hound_target

        # Priority 1: Execute immediate offensive actions while hard-rushing core.
        attack_acted, has_active_offensive_target = self.attack(
            ct, set_nav_target, execute_nav_step, enemy_core_target
        )
        if attack_acted:
            return True, enemy_core_target

        # Once the enemy core is known, always rush it unless we just acted.
        if enemy_core_target is not None:
            set_nav_target(*enemy_core_target)
            return execute_nav_step(ct), enemy_core_target

        return False, enemy_core_target

    def attack(
        self, ct: Controller, set_nav_target, execute_nav_step, enemy_core_target
    ) -> tuple[bool, bool]:
        nearby_buildings = ct.get_nearby_buildings()
        current_position = ct.get_position()
        nearby_buildings = [
            (
                e_type,
                current_position.distance_squared(ct.get_position(b)),
                b,
            )
            for b in nearby_buildings
            if (e_type := ct.get_entity_type(b)) != EntityType.CORE
        ]
        nearby_buildings.sort(key=lambda x: x[1])

        has_active_offensive_target = self.offensive_target_pos is not None

        if enemy_core_target is not None:
            core_position = Position(*enemy_core_target)
            current_position = ct.get_position()
            resource_sources = list(
                filter(
                    lambda x: (
                        x[0]
                        in (
                            EntityType.HARVESTER,
                            EntityType.BRIDGE,
                            EntityType.CONVEYOR,
                        )
                    ),
                    nearby_buildings,
                )
            )

            # === STEP 1: Visualizations (always run) ===
            for e_type, _, e_id in resource_sources:
                e_pos = ct.get_position(e_id)
                if e_type == EntityType.HARVESTER:
                    for h_dirs in CARDINAL_DIRECTIONS:
                        harv_placement_pos = e_pos.add(h_dirs)
                        target_pos = core_position.add(
                            core_position.direction_to(harv_placement_pos)
                        )
                        build_dist = harv_placement_pos.distance_squared(target_pos)
                        not_obstructing_resource = (
                            harv_placement_pos.direction_to(target_pos).opposite()
                            != h_dirs
                        )
                        if build_dist <= 32 and not_obstructing_resource:
                            ct.draw_indicator_line(
                                target_pos, harv_placement_pos, 0, 255, 0
                            )
                        elif build_dist <= 64:
                            ct.draw_indicator_line(
                                target_pos, harv_placement_pos, 255, 255, 0
                            )
                        else:
                            ct.draw_indicator_line(
                                target_pos, harv_placement_pos, 255, 0, 0
                            )
                elif (
                    e_type in (EntityType.BRIDGE, EntityType.CONVEYOR)
                    and ct.get_team(e_id) != ct.get_team()
                ):
                    stored_stuff = ct.get_stored_resource(e_id)
                    if stored_stuff:
                        self.tita_source_cache[e_id] = ct.get_current_round()
                    target_pos = core_position.add(core_position.direction_to(e_pos))
                    build_dist = e_pos.distance_squared(target_pos)
                    has_tita = (
                        ct.get_current_round() - self.tita_source_cache.get(e_id, 0)
                        <= 2
                    )
                    if build_dist <= 32 and has_tita:
                        ct.draw_indicator_line(e_pos, target_pos, 0, 255, 0)
                    elif build_dist <= 64:
                        ct.draw_indicator_line(e_pos, target_pos, 255, 255, 0)
                    else:
                        ct.draw_indicator_line(e_pos, target_pos, 255, 0, 0)

            # === STEP 2: Validate existing target ===
            if self.offensive_target_pos is not None:
                t_pos = Position(*self.offensive_target_pos)
                if (
                    t_pos.distance_squared(ct.get_position())
                    <= ct.get_vision_radius_sq()
                ):
                    existing_id = ct.get_tile_building_id(t_pos)
                    if (
                        existing_id is not None
                        and ct.get_entity_type(existing_id) == EntityType.SENTINEL
                    ):
                        if ct.get_team(existing_id) == ct.get_team():
                            self.offensive_target_pos = None
                else:
                    self.offensive_target_pos = None

            # === STEP 3: Target Acquisition (only if no target) ===
            if self.offensive_target_pos is None:
                for e_type, _, e_id in resource_sources:
                    e_pos = ct.get_position(e_id)
                    if e_type == EntityType.HARVESTER:
                        for h_dirs in CARDINAL_DIRECTIONS:
                            harv_placement_pos = e_pos.add(h_dirs)
                            target_pos = core_position.add(
                                core_position.direction_to(harv_placement_pos)
                            )
                            build_dist = harv_placement_pos.distance_squared(target_pos)
                            not_obstructing_resource = (
                                harv_placement_pos.direction_to(target_pos).opposite()
                                != h_dirs
                            )
                            if build_dist <= 32 and not_obstructing_resource:
                                self.offensive_target_pos = (
                                    harv_placement_pos.x,
                                    harv_placement_pos.y,
                                )
                                has_active_offensive_target = True
                                break
                        if self.offensive_target_pos is not None:
                            break
                    elif (
                        e_type in (EntityType.BRIDGE, EntityType.CONVEYOR)
                        and ct.get_team(e_id) != ct.get_team()
                    ):
                        if (e_pos.x, e_pos.y) in self.offensive_no_go:
                            continue
                        target_pos = core_position.add(
                            core_position.direction_to(e_pos)
                        )
                        build_dist = e_pos.distance_squared(target_pos)
                        has_tita = (
                            ct.get_current_round() - self.tita_source_cache.get(e_id, 0)
                            <= 2
                        )
                        if build_dist <= 32 and has_tita:
                            feeds, _ = self._pipeline_feeds_ally_sentinel(
                                ct, e_id, e_type
                            )
                            if not feeds:
                                self.offensive_target_pos = (e_pos.x, e_pos.y)
                                has_active_offensive_target = True
                                break

            # === STEP 4: Decoupled Execution ===
            if self.offensive_target_pos is not None:
                has_active_offensive_target = True
                t_pos = Position(*self.offensive_target_pos)
                dist_sq = t_pos.distance_squared(ct.get_position())

                if dist_sq <= ct.get_vision_radius_sq():
                    existing_id = ct.get_tile_building_id(t_pos)
                else:
                    existing_id = None

                if dist_sq <= ct.get_vision_radius_sq() and existing_id is not None:
                    e_type = ct.get_entity_type(existing_id)
                    if e_type in (EntityType.CONVEYOR, EntityType.BRIDGE):
                        feeds, no_go_key = self._pipeline_feeds_ally_sentinel(
                            ct, existing_id, e_type
                        )
                        if feeds:
                            self.offensive_no_go[self.offensive_target_pos] = (
                                ct.get_current_round()
                            )
                            self.offensive_target_pos = None
                            has_active_offensive_target = False
                            return False, False

                targeting_dir = t_pos.direction_to(core_position)

                if ct.can_build_sentinel(t_pos, targeting_dir):
                    ct.build_sentinel(t_pos, targeting_dir)
                    self.offensive_target_pos = None
                    return True, True
                if existing_id is None:
                    # Tile is empty (or out of vision). Move to it.
                    set_nav_target(t_pos.x, t_pos.y)
                    if execute_nav_step(ct):
                        if ct.can_build_sentinel(t_pos, targeting_dir):
                            ct.build_sentinel(t_pos, targeting_dir)
                            self.offensive_target_pos = None
                            has_active_offensive_target = False
                        return True, True
                else:
                    # Something is blocking the tile. Attack it to clear the way!
                    if self.attack_sqr(
                        ct, set_nav_target, execute_nav_step, existing_id
                    ):
                        # Attempt build immediately in case we destroyed it this tick
                        if ct.can_build_sentinel(t_pos, targeting_dir):
                            ct.build_sentinel(t_pos, targeting_dir)
                            self.offensive_target_pos = None
                            has_active_offensive_target = False
                            return True, True
                        return False, True
                return True, True  # Actively pursuing target, block fallback

        return False, has_active_offensive_target

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

    def _pipeline_feeds_ally_sentinel(
        self,
        ct: Controller,
        building_id: int,
        building_type: EntityType,
        visited: set[int] | None = None,
        depth: int = 0,
    ) -> tuple[bool, tuple[int, int] | None]:
        if depth > 20:
            return (False, None)
        if visited is None:
            visited = set()
        if building_id in visited:
            return (False, None)
        visited.add(building_id)

        b_pos = ct.get_position(building_id)
        my_team = ct.get_team()

        cache_key = (b_pos.x, b_pos.y)
        if cache_key in self.offensive_no_go:
            return (True, cache_key)

        tile_building = ct.get_tile_building_id(b_pos)
        if tile_building is not None:
            if ct.get_entity_type(tile_building) == EntityType.SENTINEL:
                if ct.get_team(tile_building) == my_team:
                    self.offensive_no_go[cache_key] = ct.get_current_round()
                    return (True, cache_key)

        if building_type == EntityType.CONVEYOR:
            conveyor_dir = ct.get_direction(building_id)
            next_pos = b_pos.add(conveyor_dir)
            if (
                next_pos.distance_squared(ct.get_position())
                <= ct.get_vision_radius_sq()
            ):
                next_building = ct.get_tile_building_id(next_pos)
                if next_building is not None:
                    next_type = ct.get_entity_type(next_building)
                    if next_type in (EntityType.CONVEYOR, EntityType.BRIDGE):
                        return self._pipeline_feeds_ally_sentinel(
                            ct, next_building, next_type, visited, depth + 1
                        )
                    elif next_type == EntityType.SENTINEL:
                        feeds = ct.get_team(next_building) == my_team
                        if feeds:
                            self.offensive_no_go[cache_key] = ct.get_current_round()
                            return (True, cache_key)
                        return (False, None)
            return (False, None)

        elif building_type == EntityType.BRIDGE:
            bridge_target_pos = ct.get_bridge_target(building_id)
            if (
                bridge_target_pos.distance_squared(ct.get_position())
                <= ct.get_vision_radius_sq()
            ):
                next_building = ct.get_tile_building_id(bridge_target_pos)
                if next_building is not None:
                    next_type = ct.get_entity_type(next_building)
                    if next_type in (EntityType.CONVEYOR, EntityType.BRIDGE):
                        return self._pipeline_feeds_ally_sentinel(
                            ct, next_building, next_type, visited, depth + 1
                        )
                    elif next_type == EntityType.SENTINEL:
                        feeds = ct.get_team(next_building) == my_team
                        if feeds:
                            self.offensive_no_go[cache_key] = ct.get_current_round()
                            return (True, cache_key)
                        return (False, None)
            return (False, None)

        return (False, None)

    def can_afford_sentinel(self, ct: Controller) -> bool:
        current_titanium = ct.get_global_resources()[0]
        sentinel_cost = ct.get_sentinel_cost()[0]

        if self.last_titanium is not None:
            # Only track positive growth (income) to avoid being penalized by our own spending
            delta = current_titanium - self.last_titanium
            self.titanium_history.append(max(0, delta))
        self.last_titanium = current_titanium

        # 1. Current balance check
        if current_titanium < sentinel_cost:
            return False

        # 2. Moving average income check (>= 1/4 Sentinel cost)
        if self.titanium_history:
            avg_income = sum(self.titanium_history) / len(self.titanium_history)
            if avg_income < sentinel_cost / 10:
                return False

        return True
