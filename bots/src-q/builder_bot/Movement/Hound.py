import sys

from cambc import Controller, EntityType


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
        attack_acted = self.attack_sqr(ct, set_nav_target, execute_nav_step)
        if attack_acted:
            return True, enemy_core_target

        if enemy_core_target is None:
            hound_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)
            if hound_target is None:
                return False, enemy_core_target
            enemy_core_target = hound_target

        set_nav_target(*enemy_core_target)
        return execute_nav_step(ct), enemy_core_target

    def attack_sqr(
        self,
        ct: Controller,
        set_nav_target,
        execute_nav_step,
    ) -> bool:
        nearby_buildings = ct.get_nearby_buildings()
        nearby_enemy_buildings = [
            b for b in nearby_buildings 
            if ct.get_team(b) != ct.get_team() 
            and ct.get_entity_type(b) not in (EntityType.CORE, EntityType.HARVESTER)
        ]

        if not nearby_enemy_buildings:
            return False

        current_position = ct.get_position()
        
        # Calculate (priority, -distance_sq, building_id) for each target.
        # Negative distance ensures that closer buildings win ties in priority.
        potential_targets = []
        for b_id in nearby_enemy_buildings:
            etype = ct.get_entity_type(b_id)
            priority = self.PRIORITY_MAP.get(etype, 10)
            dist_sq = current_position.distance_squared(ct.get_position(b_id))
            potential_targets.append((priority, -dist_sq, b_id))

        # Sort by priority desc, then distance asc (which is -dist_sq desc)
        potential_targets.sort(reverse=True)

        # Target the best building
        target_id = potential_targets[0][2]
        b_pos = ct.get_position(target_id)
        my_pos = ct.get_position()
        etype = ct.get_entity_type(target_id)

        # Highlight target using the requested color map
        dot_color = self.COLOR_MAP.get(etype, (255, 160, 0))  # Default: Orange
        ct.draw_indicator_dot(b_pos, *dot_color)

        # Physically walk onto the tile if not already there
        if my_pos.x != b_pos.x or my_pos.y != b_pos.y:
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
