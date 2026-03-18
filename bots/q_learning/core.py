import random
from cambc import Controller, Direction

DIRECTIONS = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST
]

class Core:
    def __init__(self):
        self.spawn_index = 0
        self.spawned = 0

    def run(self, ct: Controller):
        if ct.get_action_cooldown() == 0:
            res = ct.get_global_resources()
            if res[0] >= self.spawned*80*8*1.25-res[0]*self.spawned*0.8:  # Titanium cost for builder bot is 10
                for _ in range(8):
                    d = DIRECTIONS[self.spawn_index % 8]
                    self.spawn_index += 1
                    spawn_pos = ct.get_position().add(d)
                    
                    if ct.can_spawn(spawn_pos):
                        ct.spawn_builder(spawn_pos)
                        self.spawned+=1
                        break
