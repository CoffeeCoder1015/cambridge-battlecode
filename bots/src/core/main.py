import random

from cambc import Controller, Direction

import core 


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

class Core: 
    def __init__(self):
        self.map_height = ct.get_map_height()
        self.map_width = ct.get_map_width()

    def run(ct: Controller, player) -> None:
        if player.num_spawned < 3:
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                player.num_spawned += 1
