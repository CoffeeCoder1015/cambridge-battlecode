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
        
        # 1. Eager check: what's directly in our line of fire?
        # Gunners have a fixed direction and a get_gunner_target() method.
        target_pos = ct.get_gunner_target()
        if target_pos is not None:
            # can_fire already checks team, line of sight, and ammo
            if ct.can_fire(target_pos):
                print(f"[Gunner {ct.get_id()}] EAGER: Firing at {target_pos} in line of sight.", file=sys.stderr)
                ct.fire(target_pos)
                return
            else:
                # Debug why we aren't firing at a target in our path
                ammo = ct.get_ammo_amount()
                if ammo < 2:
                    print(f"[Gunner {ct.get_id()}] LOW AMMO: Target at {target_pos} spotted, but ammo is {ammo}", file=sys.stderr)
        
        # 2. General scan (fallback for nearby targets slightly off the center line)
        best_target = None
        best_priority = -1
        
        targets = ct.get_nearby_units() + ct.get_nearby_buildings()
        
        for t_id in targets:
            if ct.get_team(t_id) != my_team:
                e_type = ct.get_entity_type(t_id)
                priority = self.priority_map.get(e_type, 5)
                
                pos = ct.get_position(t_id)
                
                if ct.can_fire(pos):
                    if priority > best_priority:
                        best_priority = priority
                        best_target = pos
                        
        if best_target is not None:
            print(f"[Gunner {ct.get_id()}] SCAN: Firing at {best_target} (priority {best_priority})", file=sys.stderr)
            ct.fire(best_target)
