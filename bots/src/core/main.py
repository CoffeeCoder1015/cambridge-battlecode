import random
import sys
from cambc import Controller, Direction


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


import sys
from collections import Counter

import sys
from collections import Counter

class Core:
    def __init__(self):
        self.map_height = None

    def run(self, ct: Controller, player) -> None:

        if player.num_spawned < 10:
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                player.num_spawned += 1
            
