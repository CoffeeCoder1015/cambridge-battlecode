import random

from cambc import Controller, Direction


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

class Builder_bot:
    def __init__(self):
        pass

    def run(self,ct: Controller) -> None:
        for d in Direction:
            check_pos = ct.get_position().add(d)
            if ct.can_build_harvester(check_pos):
                ct.build_harvester(check_pos)
                break

        move_dir = random.choice(DIRECTIONS)
        move_pos = ct.get_position().add(move_dir)
        if ct.can_build_road(move_pos):
            ct.build_road(move_pos)
        if ct.can_move(move_dir):
            ct.move(move_dir)

        marker_pos = ct.get_position().add(random.choice(DIRECTIONS))
        if ct.can_place_marker(marker_pos):
            ct.place_marker(marker_pos, ct.get_current_round())
