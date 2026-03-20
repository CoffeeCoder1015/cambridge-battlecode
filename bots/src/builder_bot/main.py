from cambc import Controller, Direction
from .TerrainMemory import SymmetryAnalyzer

import random
import sys



DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

def run(ct: Controller) -> None:
    turn = ct.get_current_round()

    if turn % 2 == 0:
        symmetry_analyzer = SymmetryAnalyzer(ct)
        found_symmetry = symmetry_analyzer.update(ct)
        if found_symmetry != None:
            print(f"Found symmetry: {found_symmetry}", file=sys.stderr)

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

    # marker_pos = ct.get_position().add(random.choice(DIRECTIONS))
    # if ct.can_place_marker(marker_pos):
    #     ct.place_marker(marker_pos, ct.get_current_round())
