from cambc import Environment, Team, EntityType
import sys

DEBUG_PRINTS = False

'''
SymmetryAnalyzer:

Holds memory of seen objects, is only allowed to place a marker given the following 2 conditions:
1. New info by reading a friendly marker and combing that with its own knowledge, it should say this in the print when placing the marker
2. Finds a method of symetry is invalid, therefore this is new information as long as it wasnt aware of this before. (aka read it on a marker before hand it would salready know)

PropogateSymetry handles passing this information to the core.
'''

class SymmetryAnalyzer:
    MAGIC_MASK = 0x5A000000 
    
    def __init__(
        self,
        ct,
        core_pos: tuple[int, int] | None = None,
        debug_prints: bool = DEBUG_PRINTS,
    ):
        self.w = ct.get_map_width()
        self.h = ct.get_map_height()
        self.debug_prints = debug_prints
        if core_pos is None:
            cp = ct.get_position()
            self.my_core = (cp.x, cp.y)
        else:
            self.my_core = (core_pos[0], core_pos[1])
        
        self.possible = {101, 102, 103}
        self.map_history = {} 
        self.solved_sym = None
        self.sym_names = {101: "REF_X", 102: "REF_Y", 103: "ROT"}
        
        # Track what we have personally broadcasted to avoid self-spam
        self.last_broadcasted_mask = 0

        self._check_axis_overlap()

    def update_core_pos(self, core_pos: tuple[int, int]) -> None:
        new_core = (core_pos[0], core_pos[1])
        if new_core == self.my_core:
            return
        self.my_core = new_core
        self._check_axis_overlap()

    def _check_axis_overlap(self):
        cx, cy = (self.w - 1) / 2.0, (self.h - 1) / 2.0
        core_x, core_y = self.my_core

        # 3x3 core footprint reaches one tile from its center, so if the
        # center is within 1 tile of an axis, the footprint overlaps that band.
        if abs(core_x - cx) <= 1.0 and 101 in self.possible:
            self.possible.discard(101)
            if self.debug_prints:
                print(
                    f"[Bot {self.my_core}] Init: ruled out REF_X — 3x3 core overlaps vertical axis band",
                    file=sys.stderr,
                )
        if abs(core_y - cy) <= 1.0 and 102 in self.possible:
            self.possible.discard(102)
            if self.debug_prints:
                print(
                    f"[Bot {self.my_core}] Init: ruled out REF_Y — 3x3 core overlaps horizontal axis band",
                    file=sys.stderr,
                )

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

        # Snapshot possible before reading markers so we can detect marker-sourced new knowledge
        possible_before_markers = set(self.possible)

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
                if self.debug_prints:
                    print(f"TURN {ct.get_current_round()}: [Bot {(cur.x, cur.y)}] FAILED to read entity {m_id} - Error: {repr(e)}", file=sys.stderr)
                continue

        # New symmetries eliminated this turn purely from reading a nearby friendly marker
        newly_eliminated_by_marker = possible_before_markers - self.possible
        marker_gave_new_info = bool(newly_eliminated_by_marker)
             

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
                        if self.debug_prints:
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
            if self.debug_prints:
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
        # 2. This turn produced genuinely new information — either:
        #    a) A nearby friendly marker taught us something we didn't know yet, OR
        #    b) A tile mismatch invalidated a symmetry candidate this turn
        # 3. What we know must NOT already be covered by nearby markers (Echo Suppression)
        new_info_this_turn = marker_gave_new_info or bool(invalidated_mismatches)
        if my_knowledge_mask > 0 and new_info_this_turn:
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
                    if self.debug_prints:
                        eliminated_names = [
                            self.sym_names[s] for s in (101, 102, 103)
                            if s in ({101, 102, 103} - self.possible)
                        ]
                        reasons = []
                        if invalidated_mismatches:
                            mismatch_strs = [
                                f"{self.sym_names[sym]}: tile {pos} ≠ mirror {m_pos}"
                                for sym, (pos, m_pos) in invalidated_mismatches.items()
                            ]
                            reasons.append(f"tile mismatches: {', '.join(mismatch_strs)}")
                        if marker_gave_new_info:
                            marker_elim_names = [self.sym_names[s] for s in (101, 102, 103) if s in newly_eliminated_by_marker]
                            reasons.append(f"read marker: newly eliminated=[{', '.join(marker_elim_names)}]")
                        reason = " — " + " + ".join(reasons)
                        print(
                            f"TURN {ct.get_current_round()}: [Bot {(cur.x, cur.y)}] "
                            f"Placed marker at ({target_tile.x}, {target_tile.y}) "
                            f"broadcasting eliminated=[{', '.join(eliminated_names)}]{reason} "
                            f"| memory: possible=[{', '.join(self.sym_names[s] for s in sorted(self.possible))}] "
                            f"tiles_seen={len(self.map_history)} last_broadcast_mask={bin(self.last_broadcasted_mask)}",
                            file=sys.stderr,
                        )

        return self.solved_sym