from cambc import Environment, Team, EntityType
import sys

DEBUG_PRINTS = True

'''
SymmetryAnalyzer:
- Uses bitmasking (Magic Mask: 0x5A000000) to communicate.
- Echo Suppression: Only places a marker if its knowledge isn't already visible nearby.
- Road Clearing: Will destroy a ROAD to place a marker if no empty tiles are available.
'''

class SymmetryAnalyzer:
    MAGIC_MASK = 0x5A000000 
    
    def __init__(self, ct):
        self.w = ct.get_map_width()
        self.h = ct.get_map_height()
        cp = ct.get_position()
        self.my_core = (cp.x, cp.y)
        
        self.possible = {101, 102, 103}
        self.map_history = {} 
        self.solved_sym = None
        self.sym_names = {101: "REF_X", 102: "REF_Y", 103: "ROT"}
        
        # Track what we have personally broadcasted to avoid self-spam
        self.last_broadcasted_mask = 0

        self._check_axis_overlap()

    def _check_axis_overlap(self):
        cx, cy = (self.w - 1) / 2.0, (self.h - 1) / 2.0
        if abs(self.my_core[0] - cx) < 0.1:
            self.possible.discard(101)
            if DEBUG_PRINTS:
                print(f"[Bot {self.my_core}] Init: ruled out REF_X — core sits on vertical centre axis", file=sys.stderr)
        if abs(self.my_core[1] - cy) < 0.1:
            self.possible.discard(102)
            if DEBUG_PRINTS:
                print(f"[Bot {self.my_core}] Init: ruled out REF_Y — core sits on horizontal centre axis", file=sys.stderr)

    def _get_mirror(self, x, y, sym):
        if sym == 101: return (self.w - 1 - x, y)
        if sym == 102: return (x, self.h - 1 - y)
        return (self.w - 1 - x, self.h - 1 - y)

    def _get_sorted_nearby_tiles(self, ct, cur):
        cx, cy = self.my_core
        candidates = []
        for t in ct.get_nearby_tiles():
            if max(abs(t.x - cur.x), abs(t.y - cur.y)) <= 1:
                dist_sq = (t.x - cx)**2 + (t.y - cy)**2
                candidates.append((dist_sq, t))
        candidates.sort(key=lambda x: x[0])
        return [c[1] for c in candidates]

    def update(self, ct):
        # 1. Read Markers & suppression check
        # We track what is ALREADY visible on the ground nearby
        visible_info_mask = 0
        cur = ct.get_position()
        
        for m_id in ct.get_nearby_entities():
            try:
                if ct.get_entity_type(m_id) == EntityType.MARKER and ct.get_team(m_id) == ct.get_team():
                    val = ct.get_marker_value(m_id)
                    if isinstance(val, int) and (val & 0xFF000000) == self.MAGIC_MASK:
                        info_bits = val & 0x7 # Get the 3 elimination bits
                        visible_info_mask |= info_bits # Combine all nearby knowledge
                        
                        if (info_bits & 1): self.possible.discard(101)
                        if (info_bits & 2): self.possible.discard(102)
                        if (info_bits & 4): self.possible.discard(103)
            except Exception as e:
                if DEBUG_PRINTS:
                    print(f"TURN {ct.get_current_round()}: [Bot {(cur.x, cur.y)}] FAILED to read entity {m_id} - Error: {repr(e)}", file=sys.stderr)
                continue
             

        # 2. Process NEW tiles
        nearby = ct.get_nearby_tiles()
        new_tiles_found = []
        for t in nearby:
            pos = (t.x, t.y)
            if pos not in self.map_history:
                env = ct.get_tile_env(t)
                self.map_history[pos] = env
                new_tiles_found.append((pos, env))

        # 3. Incremental Elimination Logic
        invalidated_mismatches = {}
        if new_tiles_found and len(self.possible) > 1:
            invalidated = set()
            for sym in self.possible:
                for pos, val in new_tiles_found:
                    m_pos = self._get_mirror(pos[0], pos[1], sym)
                    if m_pos in self.map_history and self.map_history[m_pos] != val:
                        invalidated.add(sym)
                        invalidated_mismatches[sym] = (pos, m_pos)
                        if DEBUG_PRINTS:
                            print(
                                f"TURN {ct.get_current_round()}: [Bot {(cur.x, cur.y)}] "
                                f"Ruled out {self.sym_names[sym]} — tile {pos} ({val.value}) "
                                f"≠ mirror {m_pos} ({self.map_history[m_pos].value})",
                                file=sys.stderr,
                            )
                        break
            self.possible -= invalidated

        # 4. Finalize Solution
        if len(self.possible) == 1 and not self.solved_sym:
            self.solved_sym = list(self.possible)[0]
            if DEBUG_PRINTS:
                print(
                    f"TURN {ct.get_current_round()}: [Bot {(cur.x, cur.y)}] "
                    f"*** SYMMETRY SOLVED: {self.sym_names[self.solved_sym]} "
                    f"(eliminated {len({101,102,103} - self.possible)} of 3 candidates) ***",
                    file=sys.stderr,
                )

        # 5. Broadcast (Only if we have information NOT already on the ground nearby)
        current_eliminated = {101, 102, 103} - self.possible
        my_knowledge_mask = 0
        if 101 in current_eliminated: my_knowledge_mask |= 1
        if 102 in current_eliminated: my_knowledge_mask |= 2
        if 103 in current_eliminated: my_knowledge_mask |= 4

        # PLACEMENT CONDITION:
        # 1. We must know something (mask > 0)
        # 2. What we know must be different from what we personally last sent
        # 3. What we know must NOT already be covered by nearby markers (Echo Suppression)
        if my_knowledge_mask > 0 and my_knowledge_mask != self.last_broadcasted_mask:
            if (my_knowledge_mask & ~visible_info_mask) != 0:
                sorted_tiles = self._get_sorted_nearby_tiles(ct, cur)
                target_tile = None
                
                # Pass 1: Find open spot
                for t in sorted_tiles:
                    if ct.can_place_marker(t):
                        target_tile = t
                        break
                
                # Pass 2: Clear a ROAD if necessary - TEMP REMOVED
                # if not target_tile:
                #     for t in sorted_tiles:
                #         if ct.get_tile_env(t) == Environment.EMPTY and ct.can_destroy(t):
                #             ct.destroy(t)
                #             target_tile = t
                #             break

                if target_tile:
                    marker_val = self.MAGIC_MASK | my_knowledge_mask
                    ct.place_marker(target_tile, marker_val)
                    self.last_broadcasted_mask = my_knowledge_mask
                    if DEBUG_PRINTS:
                        eliminated_names = [
                            self.sym_names[s] for s in (101, 102, 103)
                            if s in ({101, 102, 103} - self.possible)
                        ]
                        mismatch_strs = [
                            f"{self.sym_names[sym]}: tile {pos} ≠ mirror {m_pos}"
                            for sym, (pos, m_pos) in invalidated_mismatches.items()
                        ]
                        reason = f" — from mismatches: {', '.join(mismatch_strs)}" if mismatch_strs else " — no new mismatches this turn (re-broadcasting)"
                        print(
                        f"TURN {ct.get_current_round()}: [Bot {(cur.x, cur.y)}] "
                        f"Placed marker at ({target_tile.x}, {target_tile.y}) "
                        f"broadcasting eliminated=[{', '.join(eliminated_names)}]{reason} "
                        f"| memory: possible=[{', '.join(self.sym_names[s] for s in sorted(self.possible))}] "
                        f"tiles_seen={len(self.map_history)} last_broadcast_mask={bin(self.last_broadcasted_mask)}",
                        file=sys.stderr,
                    )

        return self.solved_sym