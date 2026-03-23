import random
from cambc import Controller, Direction, Environment, Position, Team

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
        self.map_lut = None
        self.possible_symmetries = ["horizontal", "vertical", "rotational"]

    def update_symmetry(self, ct: Controller, nearby_tiles: list[Position], nearby_units: list[int]):
        w, h = self.dimensions
        cx, cy = self.ally_core_pos.x, self.ally_core_pos.y
        
        # 1. Deterministic Core-based Symmetry Confirmation
        enemy_id = 2 if ct.get_team() == Team.A else 1
        if enemy_id in nearby_units:
            enemy_pos = ct.get_position(enemy_id)
            ex, ey = enemy_pos.x, enemy_pos.y
            
            confirmed_sym = None
            if ex == w - 1 - cx and ey == cy:
                confirmed_sym = "horizontal"
            elif ex == cx and ey == h - 1 - cy:
                confirmed_sym = "vertical"
            elif ex == w - 1 - cx and ey == h - 1 - cy:
                confirmed_sym = "rotational"
            
            if confirmed_sym and confirmed_sym in self.possible_symmetries:
                self.possible_symmetries = [confirmed_sym]
                return # Core found, symmetry is deterministic
        
        # 2. Environment-based POI Matching (if not yet deterministic)
        if len(self.possible_symmetries) <= 1:
            return

        for pos in nearby_tiles:
            if self.map_lut[pos.y][pos.x] != 0:
                continue
                
            env = ct.get_tile_env(pos)
            if env == Environment.ORE_TITANIUM:
                val = 2
            elif env == Environment.WALL:
                val = 3
            elif env == Environment.ORE_AXIONITE:
                val = 4
            else:
                val = 1
                
            if val > 1:
                for sym in self.possible_symmetries:
                    sym_x, sym_y = pos.x, pos.y
                    if sym == "horizontal":
                        sym_x = w - 1 - pos.x
                    elif sym == "vertical":
                        sym_y = h - 1 - pos.y
                    elif sym == "rotational":
                        sym_x = w - 1 - pos.x
                        sym_y = h - 1 - pos.y
                        
                    if 0 <= sym_x < w and 0 <= sym_y < h:
                        sym_val = self.map_lut[sym_y][sym_x]
                        if sym_val != 0 and sym_val != val:
                            self.possible_symmetries.remove(sym)
                            
            self.map_lut[pos.y][pos.x] = val

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
            self.map_lut = [ [0] * self.dimensions[0] for _ in range(self.dimensions[1]) ]
            
            # Early elimination based on core position overlap
            w, h = self.dimensions
            cx, cy = self.ally_core_pos.x, self.ally_core_pos.y
            overlap_x = abs(2 * cx - (w - 1)) <= 2
            overlap_y = abs(2 * cy - (h - 1)) <= 2
            
            if overlap_x and "horizontal" in self.possible_symmetries:
                self.possible_symmetries.remove("horizontal")
            if overlap_y and "vertical" in self.possible_symmetries:
                self.possible_symmetries.remove("vertical")
            if overlap_x and overlap_y and "rotational" in self.possible_symmetries:
                self.possible_symmetries.remove("rotational")

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
        
        # get nearby environment and insert obstacles and ores into LUT
        self.update_symmetry(ct, nearby_tiles, nearby_units)
        
        nearby_buildings = ct.get_nearby_buildings()
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
            w, h = self.dimensions
            cx, cy = self.ally_core_pos.x, self.ally_core_pos.y
            for sym in self.possible_symmetries:
                if sym == "horizontal":
                    ct.draw_indicator_line(current_pos.add(move_direction), Position(w - 1 - cx, cy), 255, 165, 0)
                elif sym == "vertical":
                    ct.draw_indicator_line(current_pos.add(move_direction), Position(cx, h - 1 - cy), 255, 165, 0)
                elif sym == "rotational":
                    ct.draw_indicator_line(current_pos.add(move_direction), Position(w - 1 - cx, h - 1 - cy), 255, 165, 0)
        

    def do_a_bounce(self, ct, current_pos, move_direction):
        # bounce by picking direction that is to the sides or oppisite diagonals diagonals to current direction
        current_dir_idx = DIRECTIONS.index(move_direction)
        raw_bounce_directions = [ DIRECTIONS[(current_dir_idx + offset) % 8] for offset in (2, -2, 3, -3)]
        bounce_directions = filter(lambda x: ct.can_move(x) or ct.can_build_road(current_pos.add(x)), raw_bounce_directions)
        move_direction = random.choice(list(bounce_directions))
        move_dest = current_pos.add(move_direction)
        return move_direction,move_dest
