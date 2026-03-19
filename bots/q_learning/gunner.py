import sys
from cambc import Controller, EntityType

class Gunner:
    def __init__(self):
        # Priority mapping for target selection
        self.priority_map = {
            EntityType.CORE: 100,
            EntityType.ARMOURED_CONVEYOR: 95,
            EntityType.CONVEYOR: 90,
            EntityType.HARVESTER: 80,
            EntityType.FOUNDRY: 70,
            EntityType.LAUNCHER: 65,
            EntityType.GUNNER: 60,
            EntityType.SENTINEL: 50,
            EntityType.BREACH: 45,
            EntityType.BUILDER_BOT: 40,
            EntityType.BRIDGE: 25,
            EntityType.BARRIER: 12,
            EntityType.ROAD: 10,
            EntityType.MARKER: 1,
        }

    def run(self, ct: Controller) -> None:
        if ct.get_action_cooldown() > 0:
            return
            
        my_team = ct.get_team()
        best_target = None
        best_priority = -1
        
        # Combine units and buildings for targeting
        targets = ct.get_nearby_units() + ct.get_nearby_buildings()
        
        for t_id in targets:
            # Check team
            if ct.get_team(t_id) != my_team:
                e_type = ct.get_entity_type(t_id)
                priority = self.priority_map.get(e_type, 5)
                
                pos = ct.get_position(t_id)
                
                # Check if we can legally fire at this position
                if ct.can_fire(pos):
                    if priority > best_priority:
                        best_priority = priority
                        best_target = pos
                        
        if best_target is not None:
            ct.fire(best_target)
