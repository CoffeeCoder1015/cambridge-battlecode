class SymmetryAnalyzer:
    def __init__(self, ct):
        """
        Initializes the analyzer, sets up map dimensions, and runs Step 1.
        Call this exactly once during your bot's initialization (Turn 1).
        """
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        
        # Extract core coordinates. Adapt to (pos[0], pos[1]) if Battlecode 
        # API returns a tuple instead of an object with .x and .y attributes.
        core_pos = ct.get_position()
        self.core_x = core_pos.x 
        self.core_y = core_pos.y
        
        # Step 1: All 3 symmetries are possible initially.
        self.possible_symmetries = {"REF_X", "REF_Y", "ROTATIONAL"}
        
        # Memory dictionary for Step 2 & 3: {(x, y): 'Environment_Type'}
        self.mapped_terrain = {}
        
        # Run Step 1: Instant Coordinate Elimination
        self._eliminate_by_axis()

    def _eliminate_by_axis(self):
        """
        Step 1: If the core is exactly on an axis, that reflection symmetry is impossible.
        """
        center_x = (self.width - 1) / 2.0
        center_y = (self.height - 1) / 2.0

        if self.core_x == center_x:
            self.possible_symmetries.discard("REF_X")
        if self.core_y == center_y:
            self.possible_symmetries.discard("REF_Y")

    def _get_mirrored_coord(self, x, y, symmetry_type):
        """
        Calculates the mathematically mirrored coordinate for a given symmetry.
        """
        if symmetry_type == "REF_X":
            return (self.width - 1 - x, y)
        elif symmetry_type == "REF_Y":
            return (x, self.height - 1 - y)
        elif symmetry_type == "ROTATIONAL":
            return (self.width - 1 - x, self.height - 1 - y)
        return None

    def process_vision(self, ct):
        """
        Steps 2 & 3: Call this every turn for your Core and your scouting Builder Bot.
        It ingests new vision, maps it, and mathematically eliminates invalid symmetries.
        """
        # Stop processing if we've already solved it
        if self.is_solved():
            return

        visible_tiles = ct.get_nearby_tiles()
        
        for pos in visible_tiles:
            x, y = pos.x, pos.y
            
            # Skip if we already mapped this exact tile
            if (x, y) in self.mapped_terrain:
                continue
                
            env = ct.get_tile_env(pos)
            self.mapped_terrain[(x, y)] = env

            # Check this new tile against all remaining symmetries
            invalidated_symmetries = set()
            for sym in self.possible_symmetries:
                mirrored_x, mirrored_y = self._get_mirrored_coord(x, y, sym)
                
                # If we have already mapped the mirrored coordinate, they MUST match.
                if (mirrored_x, mirrored_y) in self.mapped_terrain:
                    if self.mapped_terrain[(mirrored_x, mirrored_y)] != env:
                        invalidated_symmetries.add(sym)

            # Remove invalidated symmetries from our active set
            self.possible_symmetries -= invalidated_symmetries

    def is_solved(self):
        """
        Returns True if we have narrowed the map down to 1 exact symmetry.
        """
        return len(self.possible_symmetries) == 1

    def get_enemy_core_pos(self):
        """
        Step 4: Returns the (x, y) tuple of the enemy core if mathematically proven.
        Returns None if we are still waiting on scout data.
        """
        if not self.is_solved():
            return None
            
        # Get the single remaining validated symmetry
        final_symmetry = list(self.possible_symmetries)[0]
        
        # The enemy core is simply the mirrored coordinate of our core
        return self._get_mirrored_coord(self.core_x, self.core_y, final_symmetry)