from cambc import Controller, EntityType, Position


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
        4. Execute action (launch for launchers, fire for others).
        """
        # Early exit if on cooldown
        if ct.get_action_cooldown() > 0:
            return

        my_pos = ct.get_position()
        my_team = ct.get_team()
        is_launcher = ct.get_entity_type() == EntityType.LAUNCHER

        # Find all nearby enemies
        nearby_entities = ct.get_nearby_entities()

        possible_targets = []
        for e_id in nearby_entities:
            # Skip if it's on our team
            if ct.get_team(e_id) == my_team:
                continue

            etype = ct.get_entity_type(e_id)
            
            # Launchers can only target builder bots
            if is_launcher and etype != EntityType.BUILDER_BOT:
                continue
                
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

        # Handle the best available target
        for _, _, target_pos in possible_targets:
            if is_launcher:
                if self._handle_launch(ct, target_pos):
                    return
            else:
                if self._handle_attack(ct, target_pos):
                    return

    def _handle_attack(self, ct: Controller, target_pos: Position) -> bool:
        if ct.can_fire(target_pos):
            ct.fire(target_pos)
            return True
        return False

    def _handle_launch(self, ct: Controller, target_pos: Position) -> bool:
        """
        Find a valid destination far away from the turret and launch the bot.
        """
        my_pos = ct.get_position()
        diff_x = target_pos.x - my_pos.x
        diff_y = target_pos.y - my_pos.y
        
        # Normalize and scale to max throw range (distance ~5, dist_sq 25)
        # We'll try decreasing distances from 5 down to 1
        for dist in range(5, 0, -1):
            # Avoid division by zero if diff_x and diff_y are both 0 (shouldn't happen for a target)
            # Use max(1, ...) to prevent division by zero if diff_x + diff_y is 0
            divisor = max(1, abs(diff_x) + abs(diff_y))
            dest_x = target_pos.x + int(diff_x * dist / divisor)
            dest_y = target_pos.y + int(diff_y * dist / divisor)
            
            # Basic map bounds check
            if not (0 <= dest_x < ct.get_map_width() and 0 <= dest_y < ct.get_map_height()):
                continue
                
            destination = Position(dest_x, dest_y)
            if ct.can_launch(target_pos, destination):
                ct.launch(target_pos, destination)
                return True
                
        return False