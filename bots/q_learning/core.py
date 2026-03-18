import random

from cambc import Controller, Direction


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class Core:
    def __init__(self):
        self.spawn_direction_index = 0
        self.num_spawned = 0

    def run(self, ct: Controller):
        if self.num_spawned < 8:
            spawn_pos = ct.get_position().add(
                DIRECTIONS[self.spawn_direction_index % len(DIRECTIONS)]
            )
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.spawn_direction_index += 1
                self.num_spawned += 1
