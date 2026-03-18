from cambc import Controller, Direction


DIRECTIONS = [
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
]

BUILDER_COST = 10


class Core:
    def __init__(self):
        self.spawn_index = 0

    def run(self, ct: Controller) -> None:
        if ct.get_action_cooldown() != 0:
            return

        titanium, _ = ct.get_global_resources()
        if titanium < BUILDER_COST:
            return

        core_pos = ct.get_position()
        for _ in range(len(DIRECTIONS)):
            direction = DIRECTIONS[self.spawn_index % len(DIRECTIONS)]
            self.spawn_index += 1
            spawn_pos = core_pos.add(direction)
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                return
