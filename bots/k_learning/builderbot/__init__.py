import random
from cambc import Controller, Direction, Position, Team
from .navigation import SymmetryAnalyzer

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
        
        # Movement
        self.potential_direction = None
        self.last_perturb_round = -999
        
        # Symmetry
        self.symmetry_analyzer = None


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

        # Movement
        current_pos = ct.get_position()
        if self.potential_direction is None:
            self.potential_direction = self.ally_core_pos.direction_to(current_pos)
        
        

        move_direction = self.potential_direction
        move_dest = current_pos.add(self.potential_direction)
        
        # Spreading out / Potential logic
        # Perturbation spreading
        nearby_tiles =  ct.get_nearby_tiles()
        nearby_units = ct.get_nearby_units()
        nearby_buildings = ct.get_nearby_buildings()
        
        # get nearby environment and insert obstacles and ores into LUT
        self.symmetry_analyzer.update_symmetry(ct, nearby_tiles, nearby_units)
        
        development_percentage = len(nearby_buildings) / max(1, len(nearby_tiles))
        
        # Gemini: 
        if development_percentage >= 0.3:
            k = max(1, int(15 - 14 * (development_percentage - 0.3) / 0.7))
            if self.round_number - self.last_perturb_round >= k:
                self.last_perturb_round = self.round_number
                current_dir_idx = DIRECTIONS.index(move_direction)
                raw_preturb_directions = [ DIRECTIONS[(current_dir_idx + offset) % 8] for offset in (1, -1, 2, -2)]
                preturb_directions  = filter(lambda x: ct.can_move(x) or ct.can_build_road(current_pos.add(x)), raw_preturb_directions)
                move_direction = random.choice(list( preturb_directions ))
                move_dest = current_pos.add(move_direction)

        # Build road if cannot move onto tile
        while not ct.can_move(move_direction):
            if ct.can_build_road(move_dest):
                ct.build_road(move_dest)
            else:
                move_direction,move_dest = self.do_a_bounce(ct, current_pos, move_direction)
                self.potential_direction = move_direction

        ct.move(move_direction)
        
        # draw possible enemy core positions
        if self.debug:
            self.symmetry_analyzer.draw_debug(ct)
        

    def do_a_bounce(self, ct, current_pos, move_direction):
        # bounce by picking direction that is to the sides or oppisite diagonals diagonals to current direction
        current_dir_idx = DIRECTIONS.index(move_direction)
        raw_bounce_directions = [ DIRECTIONS[(current_dir_idx + offset) % 8] for offset in (2, -2, 3, -3)]
        bounce_directions = filter(lambda x: ct.can_move(x) or ct.can_build_road(current_pos.add(x)), raw_bounce_directions)
        move_direction = random.choice(list(bounce_directions))
        move_dest = current_pos.add(move_direction)
        return move_direction,move_dest
