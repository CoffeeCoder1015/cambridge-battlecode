import random

from cambc import Controller, Direction


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


def run(ct: Controller, player) -> None:
    if player.num_spawned < 3:
        spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
        if ct.can_spawn(spawn_pos):
            ct.spawn_builder(spawn_pos)
            player.num_spawned += 1
