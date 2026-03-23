import random

from cambc import Controller, Direction


CARDINAL_DIRECTIONS = [
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
]


class GaurdedConveryMove:
    def run(self, ct: Controller) -> bool:
        options = CARDINAL_DIRECTIONS[:]
        random.shuffle(options)
        for move_dir in options:
            if ct.can_move(move_dir):
                ct.move(move_dir)
                return True
        return False
