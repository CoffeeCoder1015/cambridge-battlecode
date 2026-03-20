from cambc import Environment, Team
import sys

class SymmetryAnalyzer:
    def __init__(self, ct):
        self.w = ct.get_map_width()
        self.h = ct.get_map_height()
        cp = ct.get_position()
        self.my_core = (cp.x, cp.y)
        
        # Labels: 101: REF_X, 102: REF_Y, 103: ROT
        self.possible = {101, 102, 103}
        self.map_history = {}  # (x, y): Environment Enum
        self.solved_sym = None
        
        # Helper dictionary for readable print logs
        self.sym_names = {101: "REF_X", 102: "REF_Y", 103: "ROT"}

        self._check_axis_overlap()

    def _check_axis_overlap(self):
        # Center coordinates for a 0-indexed grid
        cx = (self.w - 1) / 2.0
        cy = (self.h - 1) / 2.0
        
        # If core is on the center line, reflection across that line is impossible
        if abs(self.my_core[0] - cx) < 0.1: 
            self.possible.discard(101)
            print(f"[Bot {self.my_core}] Immediately ruled out REF_X due to axis overlap.", file=sys.stderr)
            
        if abs(self.my_core[1] - cy) < 0.1: 
            self.possible.discard(102)
            print(f"[Bot {self.my_core}] Immediately ruled out REF_Y due to axis overlap.", file=sys.stderr)

    def _get_mirror(self, x, y, sym):
        """
        Calculates mirrored coordinates:
        REF_X: x' = w - 1 - x, y' = y
        REF_Y: x' = x, y' = h - 1 - y
        ROT:   x' = w - 1 - x, y' = h - 1 - y
        """
        if sym == 101: return (self.w - 1 - x, y)
        if sym == 102: return (x, self.h - 1 - y)
        return (self.w - 1 - x, self.h - 1 - y)

    def update(self, ct):
            # If we already know the answer, just keep returning it
            if self.solved_sym:
                return self.solved_sym

            # 1. Marker Check (Check if teammates already solved it)
            for m_id in ct.get_nearby_entities():
                try:
                    val = ct.get_marker_value(m_id)
                    if val in {101, 102, 103}:
                        self.solved_sym = val
                        print(f"[Bot {self.my_core}] Learned symmetry {self.sym_names[val]} from a teammate's marker!", file=sys.stderr)
                        return self.solved_sym
                except Exception:
                    continue

            # 2. Process NEW tiles only
            nearby = ct.get_nearby_tiles()
            new_tiles_found = []
            
            for t in nearby:
                pos = (t.x, t.y)
                if pos not in self.map_history:
                    env = ct.get_tile_env(t)
                    self.map_history[pos] = env
                    new_tiles_found.append((pos, env))

            # 3. Incremental Elimination Logic
            if new_tiles_found and len(self.possible) > 1:
                invalidated = set()
                
                for sym in self.possible:
                    for pos, val in new_tiles_found:
                        m_pos = self._get_mirror(pos[0], pos[1], sym)
                        
                        if m_pos in self.map_history:
                            if self.map_history[m_pos] != val:
                                # Clean, readable invalidation log
                                print(f"TURN {ct.get_current_round()}: [Bot {self.my_core}] Invalidated symmetry: {self.sym_names[sym]} (Mismatch between {pos} and {m_pos})", file=sys.stderr)
                                invalidated.add(sym)
                                break 
                
                self.possible -= invalidated

                # 4. Finalize Solution
                if len(self.possible) == 1:
                    self.solved_sym = list(self.possible)[0]
                    
                    # Announce the final solution clearly
                    print(f"[Bot {self.my_core}] SOLVED! Map symmetry is definitively {self.sym_names[self.solved_sym]}.", file=sys.stderr)
                    
                    # Broadcast the answer to the team
                    if ct.can_place_marker(ct.get_position()):
                        ct.place_marker(ct.get_position(), self.solved_sym)
                        print(f"[Bot {self.my_core}] Placed marker to inform team.", file=sys.stderr)
                    
                    return self.solved_sym

            # Return None if we are still "guessing"
            return None