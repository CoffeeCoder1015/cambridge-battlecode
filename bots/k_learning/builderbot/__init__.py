import random
from cambc import Controller, Direction, Position, Team
from .navigation import Navigation, SymmetryAnalyzer

DIR_VECTORS: dict[Direction, tuple[int, int]] = {
    Direction.NORTH: (0, -1),
    Direction.NORTHEAST: (1, -1),
    Direction.EAST: (1, 0),
    Direction.SOUTHEAST: (1, 1),
    Direction.SOUTH: (0, 1),
    Direction.SOUTHWEST: (-1, 1),
    Direction.WEST: (-1, 0),
    Direction.NORTHWEST: (-1, -1),
}

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

class BuilderBot:
    def __init__(self):
        self.debug = True
        self.ally_core_pos = None
        self.round_number = 0
        self.dimensions = None
        
        # Symmetry
        self.symmetry_analyzer = None

        # Movement
        self.nav = None

    def in_bounds(self,pos: Position):
        return 0 <= pos.x <= self.dimensions[0] and 0 <= pos.y <= self.dimensions[1]

    def run(self, ct: Controller):
        # const updates
        self.round_number = ct.get_current_round()

        if self.ally_core_pos is None:
            self.ally_core_pos = ct.get_position(1 if ct.get_team() == Team.A else 2)

            if self.debug:
                ct.draw_indicator_dot(self.ally_core_pos, 255, 0, 0)
        if self.dimensions is None:
            self.dimensions = ( ct.get_map_width(),ct.get_map_height ())
            self.symmetry_analyzer = SymmetryAnalyzer(self.dimensions[0], self.dimensions[1], self.ally_core_pos)
            self.nav = Navigation(self.dimensions[0],self.dimensions[1])

        # Movement
        current_pos = ct.get_position()

        
        # Spreading out / Potential logic
        # Perturbation spreading
        nearby_tiles =  ct.get_nearby_tiles()
        nearby_units = ct.get_nearby_units()
        nearby_buildings = ct.get_nearby_buildings()
        
        # get nearby environment and insert obstacles and ores into LUT
        self.symmetry_analyzer.update_symmetry(ct, nearby_tiles, nearby_units)
        
        self.nav.update_info(ct,current_pos,nearby_tiles,nearby_buildings)
        self.nav.explore(ct)

        # draw possible enemy core positions
        if self.debug:
            self.symmetry_analyzer.draw_debug(ct)
        
