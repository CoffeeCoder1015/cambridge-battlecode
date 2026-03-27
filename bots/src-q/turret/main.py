from collections import deque
from sys import stderr

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
        self.iam : EntityType | None = None
        self.radar = {}
        self.enter = {}

    def run(self, ct: Controller):
        if self.iam is None:
            self.iam = ct.get_entity_type()

        if self.iam == EntityType.LAUNCHER:
            self.launcher(ct)
        else:
            self.turret(ct)
    
    def launcher(self,ct:Controller):
        nearby_entities = ct.get_nearby_entities()
        all_enemy_builder_bots = list(filter(
            lambda x: (
                ct.get_team(x) != ct.get_team()
                and ct.get_entity_type(x) == EntityType.BUILDER_BOT
            ),
            nearby_entities,
        ))

        my_pos = ct.get_position()

        for bot in all_enemy_builder_bots:       
            pos = ct.get_position(bot)
            if bot in self.radar:
                self.radar[bot].appendleft(pos)
            else:
                self.radar[bot] = deque(maxlen=6)
                self.radar[bot].appendleft(pos)
                self.enter[bot] = pos
            
            trace = self.radar[bot]
            for i in range(0,len(trace)-1):
                ct.draw_indicator_line(trace[i],trace[i+1],255,0,0)

            if my_pos.distance_squared(pos) <= 2:
                ct.launch(pos,self.enter[bot])
                ct.draw_indicator_dot(trace[0],0,0,255)
                ct.draw_indicator_dot(self.enter[bot],0,255,0)
            

    def turret(self,ct:Controller):
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