from cambc import Controller, EntityType


class Turret:
    def __init__(self):
        # Targeting Priority: Core > Bridge > Conveyor > Builder_bot > Road
        self.priority_map = {
            EntityType.CORE: 100,
            EntityType.BRIDGE: 80,
            EntityType.CONVEYOR: 70,
            EntityType.BUILDER_BOT: 60,
            EntityType.ROAD: 50,
        }

    def run(self, ct: Controller):
        """
        Simple turret behavior:
        1. Scan for nearby enemy entities.
        2. Prioritize targets based on type: Core > Bridge > Conveyor > Builder_bot > Road.
        3. Use distance as a tie-breaker for the same priority.
        4. Fire at the highest priority target within range.
        """
        # Early exit if on cooldown
        if ct.get_action_cooldown() > 0:
            return

        my_pos = ct.get_position()
        my_team = ct.get_team()

        # Find all nearby enemies
        nearby_entities = ct.get_nearby_entities()

        possible_targets = []
        for e_id in nearby_entities:
            # Skip if it's on our team
            if ct.get_team(e_id) == my_team:
                continue

            etype = ct.get_entity_type(e_id)
            priority = self.priority_map.get(etype, 0)

            if priority > 0:
                target_pos = ct.get_position(e_id)
                if etype == EntityType.CORE:
                    target_pos = target_pos.add(target_pos.direction_to(my_pos))
                dist_sq = my_pos.distance_squared(target_pos)
                possible_targets.append((priority, dist_sq, target_pos))

        if not possible_targets:
            return

        # Sort by priority (descending) then distance (ascending)
        possible_targets.sort(key=lambda x: (-x[0], x[1]))

        # Fire at the best available target
        for _, _, target_pos in possible_targets:
            if ct.can_fire(target_pos):
                ct.fire(target_pos)
                return
