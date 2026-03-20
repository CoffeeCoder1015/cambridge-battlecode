class SignalPropagator:
    # Bitmask constants for the 3 symmetry types
    HORIZONTAL_MASK = 0b001
    VERTICAL_MASK   = 0b010
    ROTATIONAL_MASK = 0b100
    SYMMETRY_MASK   = 0b111 # 0b111 (7) covers all three bits

    def __init__(self, core_pos):
        """
        :param core_pos: The Position object of your team's core.
        """
        self.core_pos = core_pos

    def process_and_propagate(self, controller, my_bot_knowledge: int):
        """
        Reads nearby markers, combines them with the bot's own knowledge, 
        overwrites outdated markers, or smartly places a new marker closer to the core.
        
        :param controller: The Battlecode controller object.
        :param my_bot_knowledge: An int representing the symmetries this bot has personally ruled out.
        """
        # Adjust 'get_position' to the exact API call for your bot's location
        my_pos = controller.get_position()
        
        # Start with what this bot knows personally
        combined_symmetries = my_bot_knowledge & self.SYMMETRY_MASK
        
        # Assume the closest marker we know about is our current position
        closest_marker_dist = self.distance_squared(my_pos, self.core_pos)
        
        # 1. Sense nearby markers and accumulate all information
        # Adjust 'sense_nearby_markers' to the exact API method (e.g., getting friendly markers)
        nearby_markers = controller.sense_nearby_markers() 
        
        for marker in nearby_markers:
            # Extract only the symmetry bits (just in case other bits are used later)
            marker_symmetries = marker.value & self.SYMMETRY_MASK
            
            # Combine the knowledge! (Bitwise OR merges 1s perfectly)
            combined_symmetries |= marker_symmetries
            
            # Track how close the signal has gotten to the core
            dist_to_core = self.distance_squared(marker.position, self.core_pos)
            if dist_to_core < closest_marker_dist:
                closest_marker_dist = dist_to_core

        # If we still have absolutely no information to share, do nothing
        if combined_symmetries == 0:
            return

        # 2. Overwrite existing markers if we hold newer/more information
        placed_this_turn = False
        
        for marker in nearby_markers:
            marker_symmetries = marker.value & self.SYMMETRY_MASK
            
            # Smart Check: If our combined knowledge has bits (1s) that this marker doesn't have,
            # combining them with OR will result in a strictly larger integer.
            if (marker_symmetries | combined_symmetries) > marker_symmetries:
                if controller.can_place_marker(marker.position):
                    # Overwrite the marker with the new combined information
                    controller.place_marker(marker.position, combined_symmetries)
                    placed_this_turn = True
                    # Battlecode usually restricts you to 1 marker placement per turn, so we break here.
                    break 

        # 3. If we didn't overwrite, see if we can advance the signal closer to the core
        if not placed_this_turn:
            best_placement_pos = self.get_best_placement_position(controller, my_pos)
            new_dist_to_core = self.distance_squared(best_placement_pos, self.core_pos)
            
            # Only place if we are dropping the marker strictly closer to the core 
            # than ANY other marker we currently see. This prevents backward propagation.
            if new_dist_to_core < closest_marker_dist:
                if controller.can_place_marker(best_placement_pos):
                    controller.place_marker(best_placement_pos, combined_symmetries)


    def get_best_placement_position(self, controller, my_pos):
        """
        Scans tiles within the builder bot's action radius and returns the valid 
        Position that is strictly closest to the core.
        """
        best_pos = my_pos
        min_distance = self.distance_squared(my_pos, self.core_pos)
        
        # Determine your bot's action radius squared (Check game constants, e.g., 4 or 9)
        action_radius_squared = 4 
        
        # Scan all possible offsets within the action radius
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx*dx + dy*dy <= action_radius_squared:
                    
                    # Create the target position (Adjust constructor to match your Python API)
                    # This might be Position(my_pos.x + dx, my_pos.y + dy)
                    target_pos = controller.create_position(my_pos.x + dx, my_pos.y + dy) 
                    
                    # Ensure the tile is valid and we are legally allowed to place a marker
                    if controller.can_place_marker(target_pos):
                        dist = self.distance_squared(target_pos, self.core_pos)
                        
                        if dist < min_distance:
                            min_distance = dist
                            best_pos = target_pos
                            
        return best_pos

    def distance_squared(self, pos1, pos2):
        """
        Helper function to calculate squared Euclidean distance.
        Squared distance is used to save bytecode/compute overhead vs math.sqrt().
        """
        return (pos1.x - pos2.x)**2 + (pos1.y - pos2.y)**2