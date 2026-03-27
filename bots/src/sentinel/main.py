from cambc import Controller, EntityType

class Sentinel:
    def __init__(self):
        # Define the priority map once during initialization
        # Lower number = higher priority
        self.priority_map = {
            EntityType.CORE: 1,
            EntityType.HARVESTER: 2,
            EntityType.BRIDGE: 3,
            EntityType.CONVEYOR: 4
        }

    def run(self, ct: Controller) -> None:
        """
        Main logic for the Sentinel Turret executed every round.
        """
        
        # 1. Check if the turret is ready to act
        if ct.get_action_cooldown() > 0:
            return
            
        # 2. Check if the turret has ammo
        if ct.get_ammo_amount() == 0:
            return

        my_team = ct.get_team()
        
        # Get all entities (buildings and units) within vision radius
        nearby_entities = ct.get_nearby_entities()
        
        best_target_pos = None
        best_priority = 999  

        # 3. Evaluate all nearby entities
        for entity_id in nearby_entities:
            # Ensure we are only targeting enemies
            if ct.get_team(entity_id) != my_team:
                target_pos = ct.get_position(entity_id)
                
                # Check if the Sentinel's directional arc and range allow hitting this tile
                if ct.can_fire(target_pos):
                    ent_type = ct.get_entity_type(entity_id)
                    
                    # Look up priority; default to 5 for "anything else" (e.g., enemy bots)
                    current_priority = self.priority_map.get(ent_type, 5)
                    
                    # Update target if this entity has a higher priority (lower number)
                    if current_priority < best_priority:
                        best_priority = current_priority
                        best_target_pos = target_pos
                        
                        # Optimization: If we found a Core (Priority 1), lock on and stop searching
                        if best_priority == 1:
                            break

        # 4. Execute the attack on the highest priority target found
        if best_target_pos:
            ct.fire(best_target_pos)
            
            # Draw a red debug line in the replay to visualize the attack
            my_pos = ct.get_position()
            ct.draw_indicator_line(my_pos, best_target_pos, 255, 0, 0)