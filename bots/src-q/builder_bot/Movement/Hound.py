from collections import deque
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
        self.tita_source_cache = {}

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
        nearby_buildings = ct.get_nearby_buildings()
        current_position = ct.get_position()
        nearby_buildings = [ ( e_type, current_position.distance_squared(ct.get_position(b)), b,)
            for b in nearby_buildings
            if (e_type := ct.get_entity_type(b)) != EntityType.CORE
        ]
        nearby_buildings.sort(key=lambda x: x[1])

        if enemy_core_target is not None:
            core_position = Position(*enemy_core_target)
            current_position = ct.get_position()
            resource_sources = filter( lambda x: ( x[0] in (EntityType.HARVESTER, EntityType.BRIDGE, EntityType.CONVEYOR)), nearby_buildings,)

            resource_flow_graph = {}
            for e_type,_,e_id in resource_sources:
                e_pos = ct.get_position(e_id)
                if e_type == EntityType.HARVESTER:
                    for h_dirs in CARDINAL_DIRECTIONS:
                        harv_placement_pos = e_pos.add(h_dirs)
                        target_pos = core_position.add(core_position.direction_to(harv_placement_pos))
                        build_dist = harv_placement_pos.distance_squared(target_pos)
                        
                        targeting_direction = harv_placement_pos.direction_to(target_pos)
                        not_obstructing_resource = targeting_direction.opposite() != h_dirs
                        
                        if build_dist <= 32 and not_obstructing_resource:
                            dist_to_placement = ct.get_position().distance_squared(harv_placement_pos)
                            if dist_to_placement > 20:
                                set_nav_target(harv_placement_pos.x, harv_placement_pos.y)
                                if execute_nav_step(ct):
                                    return True
                            else:
                                existing_building = ct.get_tile_building_id(harv_placement_pos)
                                if existing_building is None:
                                    set_nav_target(harv_placement_pos.x, harv_placement_pos.y)
                                    if execute_nav_step(ct):
                                        if ct.can_build_sentinel(harv_placement_pos,targeting_direction):
                                            ct.build_sentinel(harv_placement_pos,targeting_direction)
                                        return True
                                elif ct.get_entity_type(existing_building) in (EntityType.CONVEYOR,EntityType.BRIDGE):
                                    if ct.get_team(existing_building) == ct.get_team():
                                        if ct.can_destroy(harv_placement_pos):
                                            ct.destroy(harv_placement_pos)
                                            if ct.can_build_sentinel(harv_placement_pos,targeting_direction):
                                                ct.build_sentinel(harv_placement_pos,targeting_direction)
                                            return True
                                    if self.attack_sqr(ct,set_nav_target,execute_nav_step,existing_building):
                                        if ct.can_build_sentinel(harv_placement_pos,targeting_direction):
                                            ct.build_sentinel(harv_placement_pos,targeting_direction)
                                        return True

                        if build_dist <= 32 and not_obstructing_resource:
                            ct.draw_indicator_line(target_pos,harv_placement_pos,0,255,0)
                        elif build_dist <= 64:
                            ct.draw_indicator_line(target_pos,harv_placement_pos,255,255,0)
                        else:
                            ct.draw_indicator_line(target_pos,harv_placement_pos,255,0,0)
                else:
                    stored_stuff = ct.get_stored_resource(e_id)
                    # Check if conveyor / bridge has had resources flow through it
                    if stored_stuff:
                        self.tita_source_cache[e_id] = ct.get_current_round() 
                    target_pos = core_position.add(core_position.direction_to(e_pos))
                    build_dist = e_pos.distance_squared(target_pos)
                    # if build_dist <= 32 and self.tita_source_cache.get(e_id) is not None:
                    #     ct.draw_indicator_line(target_pos,e_pos,0,255,0)
                    # elif build_dist <= 64:
                    #     ct.draw_indicator_line(target_pos,e_pos,255,255,0)
                    # else:
                    #     ct.draw_indicator_line(target_pos,e_pos,255,0,0)
                    if e_type == EntityType.BRIDGE:
                        bridge_target = ct.get_bridge_target(e_id)
                        bridge_source = ct.get_position(e_id)
                        resource_flow_graph[bridge_source] = (bridge_target,build_dist,self.tita_source_cache.get(e_id,0),target_pos)
                    elif e_type == EntityType.CONVEYOR:
                        conveyor_dir = ct.get_direction(e_id)
                        conveyor_source = ct.get_position(e_id)
                        conveyor_target = conveyor_source.add(conveyor_dir)
                        resource_flow_graph[conveyor_source] = (conveyor_target,build_dist,self.tita_source_cache.get(e_id,0),target_pos)
            
            for source,data in resource_flow_graph.items():
                target,build_dist,last_seen_tita,target_pos = data
                has_tita = ct.get_current_round()-last_seen_tita <= 2
                if build_dist <= 32 and has_tita:
                    ct.draw_indicator_line(source,target,0,255,0)
                    ct.draw_indicator_line(source,target_pos,0,255,0)
                elif build_dist <= 64:
                    ct.draw_indicator_line(source,target,255,255,0)
                else:
                    ct.draw_indicator_line(source,target,255,0,0)



        

        potential_targets = []
        for b_type, b_dist, b_id in nearby_buildings:
            if ct.get_team(b_id) != ct.get_team():
                priority = self.PRIORITY_MAP.get(b_type, 10)
                potential_targets.append((priority, -b_dist, b_id))

        # Sort by priority desc, then distance asc (which is -dist_sq desc)
        potential_targets.sort(reverse=True)

        if potential_targets:
            return self.attack_sqr(ct, set_nav_target, execute_nav_step, potential_targets[0][2])
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
