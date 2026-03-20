from collections import namedtuple

from cambc import EntityType, Position

_MarkerInfo = namedtuple('_MarkerInfo', ['value', 'position'])

'''
This class will propogate signals back via markers 

1. We can destory marker then do our turn so it costs nothing
2. Doesnt cost action points

Thus we should fasvour spreading all markers back to core, core will then learn the true sym (and place marker near core for bots to spawn and instantly gain the sym
And then we can say okay, now if you are X away from core and see markers now you can destory freely (THUS remove the need for any marker cleanup logic)
'''
class SignalPropagator:
    # The unique identifier for symmetry markers
    MAGIC_MASK = 0x5A000000 
    
    # 0b111 (7) covers REF_X (1), REF_Y (2), and ROT (4)
    INFO_MASK = 0x00000007 

    def __init__(self, core_pos):
        """
        :param core_pos: The Position object of your team's core.
        """
        self.core_pos = core_pos

    def process_and_propagate(self, controller, known_symmetry: int | None):
        """
        Scans markers, merges information, and pushes the signal closer 
        to the core.
        
        :param controller: The Battlecode controller
        :param known_symmetry: None, or 101 (REF_X), 102 (REF_Y), 103 (ROT)
        """
        my_pos = controller.get_position()
        
        # 0. Convert the solved symmetry into our eliminated bitmask format
        combined_mask = 0
        if known_symmetry == 101:
            # REF_X is the answer -> REF_Y (2) and ROT (4) are eliminated
            combined_mask = 0b110 
        elif known_symmetry == 102:
            # REF_Y is the answer -> REF_X (1) and ROT (4) are eliminated
            combined_mask = 0b101 
        elif known_symmetry == 103:
            # ROT is the answer -> REF_X (1) and REF_Y (2) are eliminated
            combined_mask = 0b011 

        # 1. First Pass: Accumulate all knowledge in vision
        nearby_markers = self._get_nearby_friendly_markers(controller)
        
        for marker in nearby_markers:
            # Verify it is our symmetry marker
            if (marker.value & 0xFF000000) == self.MAGIC_MASK:
                marker_info = marker.value & self.INFO_MASK
                # Bitwise OR merges any new 1s into our combined knowledge
                combined_mask |= marker_info

        # If we hold absolutely no eliminated symmetries (known_symmetry was None 
        # AND we saw no markers), do nothing
        if combined_mask == 0:
            return

        # 2. Second Pass: Find how close THIS EXACT level of knowledge has gotten
        closest_known_dist = float('inf')
        
        for marker in nearby_markers:
            if (marker.value & 0xFF000000) == self.MAGIC_MASK:
                marker_info = marker.value & self.INFO_MASK
                
                # Check if this specific marker holds ALL the bits we currently have
                if (marker_info & combined_mask) == combined_mask:
                    dist = self.distance_squared(marker.position, self.core_pos)
                    if dist < closest_known_dist:
                        closest_known_dist = dist

        # 3. Find the valid tile in our action radius closest to the core
        best_pos = self.get_best_placement_position(controller, my_pos)
        new_dist = self.distance_squared(best_pos, self.core_pos)

        # 4. The Placement Condition
        # We only place/overwrite if we are dropping it STRICTLY CLOSER to the core 
        # than the closest marker that already holds this equivalent information.
        if new_dist < closest_known_dist:
            if controller.can_place_marker(best_pos):
                # Pack the payload back into the MAGIC_MASK format
                full_marker_value = self.MAGIC_MASK | combined_mask
                controller.place_marker(best_pos, full_marker_value)


    def _get_nearby_friendly_markers(self, controller):
        """
        Returns a list of (value, position) namedtuples for all nearby friendly
        markers that carry our MAGIC_MASK signature.
        Mirrors the entity-reading pattern used in TerrainMemory.SymmetryAnalyzer.
        """
        results = []
        for m_id in controller.get_nearby_entities():
            try:
                if (controller.get_entity_type(m_id) == EntityType.MARKER
                        and controller.get_team(m_id) == controller.get_team()):
                    val = controller.get_marker_value(m_id)
                    if isinstance(val, int) and (val & 0xFF000000) == self.MAGIC_MASK:
                        pos = controller.get_position(m_id)
                        results.append(_MarkerInfo(value=val, position=pos))
            except Exception:
                continue
        return results

    def get_best_placement_position(self, controller, my_pos):
        """
        Scans tiles within the builder bot's action radius and returns the valid 
        Position that is strictly closest to the core.
        """
        best_pos = my_pos
        min_distance = self.distance_squared(my_pos, self.core_pos)
        
        # Action radius squared (adjust based on game constants, e.g., 4)
        action_radius_squared = 4 
        
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx*dx + dy*dy <= action_radius_squared:
                    target_pos = Position(my_pos.x + dx, my_pos.y + dy)
                    
                    if controller.can_place_marker(target_pos):
                        dist = self.distance_squared(target_pos, self.core_pos)
                        if dist < min_distance:
                            min_distance = dist
                            best_pos = target_pos
                            
        return best_pos

    def distance_squared(self, pos1, pos2):
        return (pos1.x - pos2.x)**2 + (pos1.y - pos2.y)**2