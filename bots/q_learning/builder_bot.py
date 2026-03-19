import sys
import math
import random
from cambc import Controller, Direction, EntityType, Environment, Position, ResourceType, Team, GameError

CORE_MARKER_MAGIC = 0xCAFEBABE

def compute_symmetry_candidates(core_pos: Position, map_w: int, map_h: int) -> list:
    """Return 3 candidate enemy core positions:
       horizontal mirror, vertical mirror, rotational (180°)."""
    cx, cy = core_pos.x, core_pos.y
    return [
        Position(map_w - 1 - cx, map_h - 1 - cy),  # rotational (180°) — most common
        Position(map_w - 1 - cx, cy),                # horizontal (left↔right)
        Position(cx, map_h - 1 - cy),                # vertical (top↔bottom)
    ]

def get_core_boundary(core_pos: Position, map_w: int, map_h: int) -> list[Position]:
    """Return the 16 tiles adjacent (cardinal+diagonal) to a 3x3 core centered at core_pos, filtered by map bounds."""
    x, y = core_pos.x, core_pos.y
    candidates = []
    # Around the 3x3 (x-1..x+1, y-1..y+1), the boundary is at x-2, x+2, y-2, y+2
    for i in range(-1, 2):
        candidates.append(Position(x + i, y - 2))  # North (x-1, x, x+1)
        candidates.append(Position(x + i, y + 2))  # South
        candidates.append(Position(x - 2, y + i))  # West
        candidates.append(Position(x + 2, y + i))  # East

    # Plus the 4 diagonal corner adjacent tiles
    candidates.append(Position(x - 2, y - 2))
    candidates.append(Position(x + 2, y - 2))
    candidates.append(Position(x - 2, y + 2))
    candidates.append(Position(x + 2, y + 2))
    
    return [p for p in candidates if 0 <= p.x < map_w and 0 <= p.y < map_h]

def has_incoming_titanium(ct: Controller, build_pos: Position) -> bool:
    """Check if any adjacent conveyor (any team) flows directly into this build position and holds titanium."""
    for d in DIRECTIONS:
        adj_pos = build_pos.add(d)
        try:
            b_id = ct.get_tile_building_id(adj_pos)
            if b_id is not None:
                b_type = ct.get_entity_type(b_id)
                if b_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                    # Conveyor at adj_pos must be pointing to build_pos, which is d.opposite()
                    if ct.get_direction(b_id) == d.opposite():
                        # Check for titanium
                        if ct.get_stored_resource(b_id) == ResourceType.TITANIUM:
                            return True
        except Exception:
            pass
    return False

DIR_VECTORS: dict[Direction, tuple[int, int]] = {
    Direction.NORTH:     ( 0, -1),
    Direction.NORTHEAST: ( 1, -1),
    Direction.EAST:      ( 1,  0),
    Direction.SOUTHEAST: ( 1,  1),
    Direction.SOUTH:     ( 0,  1),
    Direction.SOUTHWEST: (-1,  1),
    Direction.WEST:      (-1,  0),
    Direction.NORTHWEST: (-1, -1),
}

def dir_dot(a: Direction, b: Direction) -> int:
    if a not in DIR_VECTORS or b not in DIR_VECTORS:
        return 0
    ax, ay = DIR_VECTORS[a]
    bx, by = DIR_VECTORS[b]
    return ax * bx + ay * by

def is_backward(d: Direction, spawn_direction: Direction) -> bool:
    return dir_dot(d, spawn_direction) <= 0

def gaussian(x: float, variance: float) -> float:
    if variance <= 0:
        return 1.0 if x == 2 else 0.0 # Strict mapping if variance is exactly 0
    return math.exp(-(x - 2)**2 / (2 * variance))

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

def vec_to_dir(dx: int, dy: int) -> Direction:
    """Snap an (dx, dy) vector to the nearest Direction enum."""
    # Clamp to -1..1
    dx = max(-1, min(1, dx))
    dy = max(-1, min(1, dy))
    if dx == 0 and dy == 0:
        return Direction.NORTH  # Fallback
    for d, vec in DIR_VECTORS.items():
        if vec == (dx, dy):
            return d
    return Direction.NORTH  # Fallback

def reflect_direction(heading: Direction, ct: 'Controller', my_pos) -> Direction:
    """Reflect heading off blocking surfaces via vector math.
    Probes adjacent tiles to determine which axis is blocked,
    then flips the blocked component of the heading vector."""
    hx, hy = DIR_VECTORS[heading]
    
    # We probe the cardinal directions (axes) to find the wall normal.
    # If moving diagonally (1, -1), we check East (1, 0) and North (0, -1).
    x_blocked = False
    y_blocked = False
    
    def is_static_block(pos):
        try:
            env = ct.get_tile_env(pos)
            if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                return True
            if ct.get_tile_building_id(pos) is not None:
                # Friendly buildings (like conveyors) are passable, but if we are STUCK 
                # and probing, we consider them potentially part of the 'wall' 
                # if they aren't helping us progress. For now, only hard walls.
                return True
        except Exception:
            return True # Map edge
        return False

    if hx != 0:
        if is_static_block(my_pos.add(vec_to_dir(hx, 0))):
            x_blocked = True
    
    if hy != 0:
        if is_static_block(my_pos.add(vec_to_dir(0, hy))):
            y_blocked = True
            
    # If it's a 45 degree movement and we hit a 'corner' (neither axis was clearly blocked 
    # but the diagonal was), we need to decide which axis to flip. 
    if not x_blocked and not y_blocked:
        # Check the actual diagonal we tried to move to
        if is_static_block(my_pos.add(heading)):
            # If front-diagonal is blocked, but cardinals aren't, 
            # we might be hitting a thin corner. Flip both (retroreflection).
            x_blocked = True
            y_blocked = True
    
    # Reflect blocked components
    rx = -hx if x_blocked else hx
    ry = -hy if y_blocked else hy
    
    # Final fallback: if we are still going the same way, just invert (shouldn't happen if blocked)
    if rx == hx and ry == hy:
        rx, ry = -hx, -hy
        
    return vec_to_dir(rx, ry)

class Builder_bot:
    def __init__(self):
        # MVP 1 state
        self.initialized = False
        self.mode = "builder"
        self.core_pos = None
        self.spawn_direction = None
        self.conveyor_budget = 20
        
        # New movement logic
        self.tasks = []
        self.vacated_task = None
        self.steps_on_heading = 0
        self.prev_pos = None
        self.stuck_counter = 0
        self.steps_since_resample = 0
        self.target_ore_pos = None
        self.last_built_pos = None  # Tail of our conveyor chain
        self.heading = None
        
        # Context Aware
        self.current_quadrant = None
        self.ticks_in_quadrant = 0

        # Bug2 and Advanced Tactics
        self.navigation_mode = "EXPLORE" # EXPLORE, BUG2_NAV, BUG2_WALL
        self.m_line_start = None
        self.bug2_hit_point = None
        self.bug2_closest_dist = 999999
        self.bug2_wall_dir = 1 # 1 for right, -1 for left
        self.bug2_wall_steps = 0     # Break loops

        # Symmetry-based Core Hunting (replaces greedy self-destruct)
        self.attack_phase = False          # True once enemy buildings spotted
        self.symmetry_candidates = []      # list[Position] — the 3 candidate core positions
        self.current_candidate_idx = 0     # which candidate we're navigating to
        self.visited_candidates = set()    # indices already checked
        self.enemy_core_pos = None         # confirmed enemy core position
        self.harvesters_defended = set()   # ore positions where we already built a defensive turret

    def get_orthogonal_step(self):
        dx, dy = DIR_VECTORS[self.spawn_direction]
        choices = []
        if dx > 0:
            choices.append(Direction.EAST)
        elif dx < 0:
            choices.append(Direction.WEST)
        if dy > 0:
            choices.append(Direction.SOUTH)
        elif dy < 0:
            choices.append(Direction.NORTH)
        
        if len(choices) == 1:
            return choices[0]
        else:
            return choices[self.steps_on_heading % 2]

    def _is_on_m_line(self, pos: Position, target_pos: Position) -> bool:
        if self.m_line_start is None or target_pos is None:
            return False
        
        x1, y1 = self.m_line_start.x, self.m_line_start.y
        x2, y2 = target_pos.x, target_pos.y
        x, y = pos.x, pos.y
        
        # Check if between points (bounding box check with small padding)
        if not (min(x1, x2) - 1 <= x <= max(x1, x2) + 1 and min(y1, y2) - 1 <= y <= max(y1, y2) + 1):
            return False
            
        # Point to line distance: Area of parallelogram / base length
        dist = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1)
        length_sq = (x2 - x1)**2 + (y2 - y1)**2
        
        if length_sq == 0:
            return True
            
        # dist / sqrt(length_sq) < tolerance => dist^2 <= tolerance^2 * length_sq
        # A tolerance of 0.75 is good for integer grid crossings
        if dist**2 > 0.6 * length_sq:
            return False
            
        return True

    def _pave_road_behind(self, ct: Controller, old_pos: Position):
        new_pos = ct.get_position()
        if old_pos != new_pos and ct.get_action_cooldown() == 0:
            if ct.get_global_resources()[0] >= 1:
                if ct.can_build_road(old_pos):
                    ct.build_road(old_pos)

    def _bug2_step(self, ct: Controller, target_pos: Position):
        my_pos = ct.get_position()
        dist_to_target = my_pos.distance_squared(target_pos)
        
        if self.navigation_mode == "BUG2_NAV":
            target_dir = my_pos.direction_to(target_pos)
            if ct.can_move(target_dir):
                ct.move(target_dir)
                self._pave_road_behind(ct, my_pos)
            else:
                # Hit a wall
                self.navigation_mode = "BUG2_WALL"
                self.bug2_hit_point = my_pos
                self.bug2_closest_dist = dist_to_target
                # Pick a wall following direction (right)
                self.bug2_wall_dir = 1 
                self._bug2_step(ct, target_pos) # Recursive call to start wall following
                return
                
        elif self.navigation_mode == "BUG2_WALL":
            if not hasattr(self, 'bug2_heading') or self.bug2_heading is None:
                self.bug2_heading = my_pos.direction_to(target_pos)

            # True wall following: try to turn into the wall, then sweep away from it
            # If wall is on the right, turn right 90 deg, then scan leftwards
            d = self.bug2_heading.rotate_right().rotate_right() if self.bug2_wall_dir == 1 else self.bug2_heading.rotate_left().rotate_left()
            
            found = False
            for _ in range(8):
                if ct.can_move(d):
                    ct.move(d)
                    self._pave_road_behind(ct, my_pos)
                    self.bug2_heading = d
                    found = True
                    break
                d = d.rotate_left() if self.bug2_wall_dir == 1 else d.rotate_right()
            # Check if traversing wall too long (trapped in a concave base)
            self.bug2_wall_steps += 1
            if self.bug2_wall_steps > 40:
                print(f"[{ct.get_id()}] BUG2: Trapped tracing wall for 40 steps! Aborting to explore.", file=sys.stderr)
                self.navigation_mode = "EXPLORE"
                self.bug2_wall_steps = 0
                if hasattr(self, 'spawn_direction'):
                    self.spawn_direction = self.spawn_direction.opposite()
                return

            if found:
                # Check if we are back on m-line and closer than hit point
                new_pos = ct.get_position()
                if self._is_on_m_line(new_pos, target_pos) and new_pos.distance_squared(target_pos) < self.bug2_closest_dist:
                    print(f"[{ct.get_id()}] BUG2: Back on m-line, resuming NAV", file=sys.stderr)
                    self.navigation_mode = "BUG2_NAV"
                    self.bug2_heading = None
                    self.bug2_wall_steps = 0

    def _aggressive_sabotage(self, ct: Controller):
        """Targeted attack: scan for enemy buildings, compute symmetry candidates,
        and systematically hunt the enemy core to place gunners."""
        my_pos = ct.get_position()
        my_team = ct.get_team()

        enemy_buildings = ct.get_nearby_buildings()
        
        best_target = None
        max_priority = -1
        found_enemy_core = None
        
        priority_map = {
            EntityType.HARVESTER: 10,
            EntityType.FOUNDRY: 15,
            EntityType.CORE: 100,
            EntityType.BREACH: 12,
            EntityType.GUNNER: 8,
            EntityType.CONVEYOR: 2,
            EntityType.ROAD: 1,
        }
        my_team = ct.get_team()
        enemy_team = Team.B if my_team == Team.A else Team.A

        # --- SHARED INTEL: Check for core discovery markers ---
        if self.enemy_core_pos is None:
            near_buildings = ct.get_nearby_buildings()
            for b_id in near_buildings:
                if ct.get_entity_type(b_id) == EntityType.MARKER and ct.get_team(b_id) == my_team:
                    val = ct.get_marker_value(b_id)
                    if (val >> 16) == (CORE_MARKER_MAGIC >> 16):
                        ex = (val >> 8) & 0xFF
                        ey = val & 0xFF
                        self.enemy_core_pos = Position(ex, ey)
                        self.enemy_core_confirmed = True
                        print(f"[{ct.get_id()}] RECEIVED CORE INTEL via marker: {self.enemy_core_pos}", file=sys.stderr)
                        break

        # Scan nearby entities for CORE (enemy)
        buildings = ct.get_nearby_buildings()
        for b_id in buildings:
            if ct.get_entity_type(b_id) == EntityType.CORE and ct.get_team(b_id) == enemy_team:
                new_pos = ct.get_position(b_id)
                if self.enemy_core_pos != new_pos:
                    self.enemy_core_pos = new_pos
                    self.enemy_core_confirmed = True
                    print(f"[{ct.get_id()}] ENEMY CORE CONFIRMED at {self.enemy_core_pos}! Broadcasting...", file=sys.stderr)
                    # Broadcast! Pack magic (upper 16) and coordinates (lower 16)
                    # MAGIC = 0xCAFEBABE. Upper 16 = 0xCAFE.
                    packed = ((CORE_MARKER_MAGIC >> 16) << 16) | (new_pos.x << 8) | new_pos.y
                    if ct.can_place_marker(my_pos):
                        ct.place_marker(my_pos, packed)
                        print(f"[{ct.get_id()}] MARKER PLACED: {hex(packed)}", file=sys.stderr)
                break
        
        for b_id in enemy_buildings:
            if ct.get_team(b_id) != my_team:
                b_type = ct.get_entity_type(b_id)
                b_pos = ct.get_position(b_id)
                priority = priority_map.get(b_type, 5)
                if b_type == EntityType.CORE:
                    found_enemy_core = b_pos
                if priority > max_priority:
                    max_priority = priority
                    best_target = b_pos
                elif priority == max_priority:
                    if best_target is None or my_pos.distance_squared(b_pos) < my_pos.distance_squared(best_target):
                        best_target = b_pos

        # If we just found the enemy core, lock it in immediately
        if found_enemy_core is not None:
            self.enemy_core_pos = found_enemy_core
            self.attack_phase = True
            print(f"[{ct.get_id()}] ENEMY CORE CONFIRMED at {found_enemy_core}!", file=sys.stderr)

        # --- TRIGGER: First enemy sighting activates symmetry hunt ---
        if not self.attack_phase and best_target is not None and self.core_pos is not None:
            map_w = ct.get_map_width()
            map_h = ct.get_map_height()
            self.symmetry_candidates = compute_symmetry_candidates(self.core_pos, map_w, map_h)
            self.current_candidate_idx = 0
            self.visited_candidates = set()
            self.attack_phase = True
            print(f"[{ct.get_id()}] ATTACK PHASE: Enemy spotted! "
                  f"Symmetry candidates: {self.symmetry_candidates}", file=sys.stderr)

        if not self.attack_phase:
            return False

        # --- ATTACK PHASE: Navigate to candidates or confirmed core ---
        my_team = ct.get_team()
        enemy_team = Team.B if my_team == Team.A else Team.A

        # If we have a confirmed core position, go straight for it
        if self.enemy_core_pos is not None:
            target_pos = self.enemy_core_pos
            ct.draw_indicator_line(my_pos, target_pos, 255, 0, 0)
            dist_sq_to_core = my_pos.distance_squared(target_pos)

            map_w, map_h = ct.get_map_width(), ct.get_map_height()
            boundary = get_core_boundary(target_pos, map_w, map_h)


            # --- MVP 2: Enemy-side turret placement (on boundary) ---
            # Priority 1: Clear and build turrets on the 16 core-adjacent tiles.
            if dist_sq_to_core <= 15:
                for b_tile in boundary:
                    if my_pos.distance_squared(b_tile) <= 2:
                        if ct.is_tile_empty(b_tile) or b_tile == my_pos:
                            # [FIX 6] Only build Gunner if it has incoming titanium!
                            if has_incoming_titanium(ct, b_tile):
                                gunner_cost = ct.get_gunner_cost()[0]
                                if ct.get_global_resources()[0] >= gunner_cost and ct.get_action_cooldown() == 0:
                                    build_dir = b_tile.direction_to(target_pos)
                                    if ct.can_build_gunner(b_tile, build_dir):
                                        ct.build_gunner(b_tile, build_dir)
                                        print(f"[{ct.get_id()}] MVP2: PLACED GUNNER at {b_tile}!", file=sys.stderr)
                                        # Move AWAY immediately to make space for more
                                        away_dir = build_dir.opposite()
                                        if ct.can_move(away_dir):
                                            ct.move(away_dir)
                                        return True
                            else:
                                # [FIX 6] Not powered? Let MVP 3 bridge it!
                                # Continue to Greedy Linker logic below
                                pass

            # --- MVP 3: Active Siege Logistics (Greedy Linker) ---
            # Priority 2: Form multi-tile supply chains to unpowered turrets.
            unpowered_turrets = []
            nearby_b = ct.get_nearby_buildings()
            for b_id in nearby_b:
                if ct.get_team(b_id) == my_team and ct.get_entity_type(b_id) == EntityType.GUNNER:
                    b_p = ct.get_position(b_id)
                    if not has_incoming_titanium(ct, b_p):
                        unpowered_turrets.append(b_p)

            target_tiles = list(unpowered_turrets) # Use list to avoid modifying the same ref
            if not target_tiles:
                # [FIX 7] Catch-22: Supply the boundary FIRST
                for b_tile in boundary:
                    try:
                        if ct.is_tile_empty(b_tile) and ct.get_global_resources()[0] >= 10:
                            target_tiles.append(b_tile)
                    except GameError:
                        pass
            
            if target_tiles:
                # Find the best tile to feed and the best source to pull from
                best_t = min(target_tiles, key=lambda p: my_pos.distance_squared(p))
                
                # Scan for sources in a 36-tile radius (Core vision)
                source_pos = None
                for b_id in nearby_b:
                    try:
                        b_p = ct.get_position(b_id)
                        b_type = ct.get_entity_type(b_id)
                        if b_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.HARVESTER):
                            # Prioritize sources that ALREADY have titanium
                            if ct.get_stored_resource(b_id) == ResourceType.TITANIUM:
                                source_pos = b_p
                                break # Found a perfect source
                            elif source_pos is None:
                                source_pos = b_p # Potential source
                    except Exception:
                        pass
                
                
                if source_pos is not None:
                    # If we are adjacent to the turret, build into it!
                    dist_to_turret = my_pos.distance_squared(best_t)
                    if dist_to_turret <= 2:
                        bridge_dir = my_pos.direction_to(best_t)
                        if ct.can_build_conveyor(my_pos, bridge_dir):
                            ct.build_conveyor(my_pos, bridge_dir)
                            print(f"[{ct.get_id()}] MVP3: LINK - Feeding turret at {best_t}", file=sys.stderr)
                            # Move away (perpendicular or back) to make room for others
                            away_dir = bridge_dir.rotate_left().rotate_left() 
                            if ct.can_move(away_dir):
                                ct.move(away_dir)
                            return True
                    
                    # If we are between source and turret, move to fill the gap
                    elif dist_to_turret <= 36:
                        # Move toward the turret to form the next link
                        move_dir = my_pos.direction_to(best_t)
                        if ct.can_move(move_dir):
                            ct.move(move_dir)
                            return True

            # --- MVP 1.1: Core Hugging (Self-destruct as LAST RESORT) ---
            try:
                curr_b_id = ct.get_tile_building_id(my_pos)
                if curr_b_id is not None:
                    b_team = ct.get_team(curr_b_id)
                    curr_type = ct.get_entity_type(curr_b_id)
                    if b_team == enemy_team and curr_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.ROAD):
                        if dist_sq_to_core <= 8:
                            print(f"[{ct.get_id()}] MVP1.1: LAST RESORT - Sabotaging {curr_type.value} at {my_pos}!", file=sys.stderr)
                            ct.self_destruct()
                            return True
            except GameError:
                pass

            # --- MVP 2.3: Congestion Relief (The 'Backoff' Role) ---
            # Priority 3: If on or near the boundary but idle, move out to 3+ tiles distance.
            on_boundary = my_pos in boundary
            if on_boundary:
                # If we're not building or sabotaging, get out of the way!
                escape_dir = my_pos.direction_to(target_pos).opposite()
                if ct.can_move(escape_dir):
                    ct.move(escape_dir)
                    return True
                else:
                    # Random wiggle to avoid gridlock
                    wiggle = random.choice([escape_dir.rotate_left(), escape_dir.rotate_right()])
                    if ct.can_move(wiggle):
                        ct.move(wiggle)
                        return True
            
            # --- MVP 2.2: Invasive Sabotage (Clearing Path for Feeders) ---
            # Blow up any enemy conveyor that blocks a potential feeder path.
            if dist_sq_to_core <= 40:
                for d in DIRECTIONS:
                    check_pos = my_pos.add(d)
                    try:
                        b_id = ct.get_tile_building_id(check_pos)
                        if b_id is not None and ct.get_team(b_id) == enemy_team:
                            if ct.get_stored_resource(b_id) == ResourceType.TITANIUM:
                                if my_pos == check_pos:
                                    ct.self_destruct()
                                    return True
                                elif ct.can_move(d):
                                    ct.move(d)
                                    return True
                    except Exception:
                        pass

            # --- NAVIGATION: Approach with patience if blocked ---
            on_boundary = my_pos in boundary
            best_b_tile = min(boundary, key=lambda p: my_pos.distance_squared(p))
            # Don't swarm too tightly if already lots of bots are there
            if not on_boundary and dist_sq_to_core <= 20:
                # Count nearby allies
                allies_near = 0
                for a_id in ct.get_nearby_units():
                    if ct.get_team(a_id) == my_team:
                        allies_near += 1
                if allies_near > 5:
                    # Too crowded, wait here as a reserve
                    return True
            # --- APPROACH: Move closer to the core boundary ---
            move_dir = my_pos.direction_to(best_b_tile)
            potential_moves = [move_dir, move_dir.rotate_left(), move_dir.rotate_right()]
            
            # Try to move into the BEST boundary tile
            for d in potential_moves:
                if ct.can_move(d):
                    ct.move(d)
                    return True
            
            # If blocked, try to move toward ANY boundary tile
            for b_tile in boundary:
                if my_pos.distance_squared(b_tile) <= 2:
                    d = my_pos.direction_to(b_tile)
                    if ct.can_move(d):
                        ct.move(d)
                        return True

            return True  # Terminate turn if near core and active

        # No confirmed core yet — cycle through symmetry candidates
        if self.current_candidate_idx >= len(self.symmetry_candidates):
            # All candidates visited, none had the core. Fall back to explore.
            print(f"[{ct.get_id()}] ATTACK: All symmetry candidates exhausted. Resuming explore.", file=sys.stderr)
            self.attack_phase = False
            return False

        # Skip already-visited candidates
        while (self.current_candidate_idx in self.visited_candidates
               and self.current_candidate_idx < len(self.symmetry_candidates)):
            self.current_candidate_idx += 1
        if self.current_candidate_idx >= len(self.symmetry_candidates):
            self.attack_phase = False
            return False

        candidate_pos = self.symmetry_candidates[self.current_candidate_idx]


        dist_sq = my_pos.distance_squared(candidate_pos)

        if dist_sq <= 36:  # Within core vision radius — scan for enemy core
            # Check if enemy core is here
            core_here = False
            for b_id in ct.get_nearby_buildings():
                if ct.get_team(b_id) != my_team and ct.get_entity_type(b_id) == EntityType.CORE:
                    self.enemy_core_pos = ct.get_position(b_id)
                    core_here = True
                    print(f"[{ct.get_id()}] ATTACK: Found enemy core at candidate #{self.current_candidate_idx}!", file=sys.stderr)
                    break

            if core_here:
                return self._aggressive_sabotage(ct)  # Re-enter with confirmed core

            # Not here — mark visited, advance
            print(f"[{ct.get_id()}] ATTACK: Candidate #{self.current_candidate_idx} ({candidate_pos}) clear. Moving on.", file=sys.stderr)
            self.visited_candidates.add(self.current_candidate_idx)
            self.current_candidate_idx += 1
            self.navigation_mode = "EXPLORE"  # Reset nav for next candidate
            return False  # Let main loop handle next tick

        # Not close enough — Bug2 navigate to this candidate
        if self.navigation_mode == "EXPLORE":
            self.navigation_mode = "BUG2_NAV"
            self.bug2_target_pos = candidate_pos
            self.bug2_target_threshold = 36
            self.m_line_start = my_pos
            self.bug2_closest_dist = dist_sq
            self.bug2_wall_steps = 0
            print(f"[{ct.get_id()}] ATTACK: Navigating to candidate #{self.current_candidate_idx} at {candidate_pos}", file=sys.stderr)
        return False  # Bug2 intercept handles movement

    def _try_opportunistic_gunner(self, ct: Controller) -> bool:
        """If a high-value enemy target is nearby, try to plant a gunner near it.
        Only places a turret if there's an enemy conveyor flowing titanium into the build tile."""
        my_pos = ct.get_position()
        my_team = ct.get_team()
        gunner_cost = ct.get_gunner_cost()[0]
        if ct.get_global_resources()[0] < gunner_cost or ct.get_action_cooldown() > 0:
            return False

        for b_id in ct.get_nearby_buildings():
            if ct.get_team(b_id) != my_team:
                b_type = ct.get_entity_type(b_id)
                if b_type in (EntityType.HARVESTER, EntityType.FOUNDRY, EntityType.CORE,
                              EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH):
                    b_pos = ct.get_position(b_id)
                    if my_pos.distance_squared(b_pos) <= 13:
                        for d in DIRECTIONS:
                            build_pos = my_pos.add(d)
                            dist_to_target = build_pos.distance_squared(b_pos)
                            if 2 < dist_to_target <= 8:
                                # Pre-check: is there titanium flowing directly into THIS build tile?
                                if has_incoming_titanium(ct, build_pos):
                                    build_dir = build_pos.direction_to(b_pos)
                                    if ct.can_build_gunner(build_pos, build_dir):
                                        ct.build_gunner(build_pos, build_dir)
                                        print(f"[{ct.get_id()}] OPPORTUNISTIC: Planted Gunner against {b_type.value}!", file=sys.stderr)
                                        return True
        return False



    def return_to_core(self, ct: 'Controller'):
        if self.navigation_mode == "EXPLORE":
            print(f"[{ct.get_id()}] Initiating return to core via Bug2", file=sys.stderr)
            self.navigation_mode = "BUG2_NAV"
            self.bug2_target_pos = self.core_pos
            self.m_line_start = ct.get_position()
            self.bug2_closest_dist = self.m_line_start.distance_squared(self.core_pos)

    def _initialize_first_round(self, ct: Controller):
        my_pos = ct.get_position()
        
        # Scan nearby entities for CORE
        buildings = ct.get_nearby_buildings()
        for b_id in buildings:
            if ct.get_entity_type(b_id) == EntityType.CORE and ct.get_team(b_id) == ct.get_team():
                self.core_pos = ct.get_position(b_id)
                break
                
        if self.core_pos is not None:
            dx = my_pos.x - self.core_pos.x
            dy = my_pos.y - self.core_pos.y
            for d, vec in DIR_VECTORS.items():
                if vec[0] == dx and vec[1] == dy:
                    self.spawn_direction = d
                    break
                    
            if dx != 0 and dy != 0:
                # Diagonal spawn needs an extra orthogonal elbow to input into the core
                elbow = my_pos.add(Direction.EAST) if dx > 0 else my_pos.add(Direction.WEST)
                elbow_to_core = elbow.direction_to(self.core_pos)
                my_to_elbow = my_pos.direction_to(elbow)
                
                self.tasks.append(("conveyor", elbow, elbow_to_core))
                self.vacated_task = ("conveyor", my_pos, my_to_elbow)
            else:
                # Orthogonal spawn
                self.vacated_task = ("conveyor", my_pos, my_pos.direction_to(self.core_pos))
                
        if self.spawn_direction is None:
            self.spawn_direction = Direction.NORTH
            
        self.initialized = True
        self._resample_heading(ct)
        print(f"[{ct.get_id()}] Initialized. Core: {self.core_pos}, SpawnDir: {self.spawn_direction.name}", file=sys.stderr)

    def _resample_heading(self, ct: Controller):
        # 1. Sample density
        buildings = ct.get_nearby_buildings()
        my_team = ct.get_team()
        ally_conveyors = sum(1 for b in buildings if ct.get_team(b) == my_team and ct.get_entity_type(b) == EntityType.CONVEYOR)
        
        # 2. Compute variance based on percentage coverage
        vision_tiles = len(ct.get_nearby_tiles())
        self.local_coverage = ally_conveyors / max(1.0, float(vision_tiles))
        coverage = self.local_coverage
        max_variance = 2.0
        # If coverage is high, variance shrinks to 0 so it pushes straight out. 
        # This straight movement also naturally patches gaps in pipelines.
        density_scale = max_variance * max(0.01, (1.0 - coverage * 4.0))
        
        # 3. Compute resample interval based on density
        min_interval = 2
        base_interval = 12
        interval_scale = 5.0
        self.steps_since_resample = max(min_interval, base_interval - int(density_scale * interval_scale))

        # 4. Generate candidate weights
        valid_directions = [d for d in DIRECTIONS if not is_backward(d, self.spawn_direction)]
        weights = [gaussian(dir_dot(d, self.spawn_direction), variance=density_scale) for d in valid_directions]
        
        if sum(weights) == 0:
            self.heading = self.spawn_direction
        else:
            self.heading = random.choices(valid_directions, weights=weights)[0]

    def run(self, ct: Controller) -> None:
        if not self.initialized:
            self._initialize_first_round(ct)
            return

        my_pos = ct.get_position()
        ct.draw_indicator_dot(my_pos, 0, 0, 255)

        # 0.1 Context Aware Movement (Quadrant Tracking)
        if self.mode == "builder" and not self.attack_phase and self.navigation_mode == "EXPLORE":
            map_w = ct.get_map_width()
            map_h = ct.get_map_height()
            cx = max(1, map_w // 2)
            cy = max(1, map_h // 2)
            qx = 0 if my_pos.x < cx else 1
            qy = 0 if my_pos.y < cy else 1
            quadrant = (qx, qy)
            
            if self.current_quadrant is None:
                self.current_quadrant = quadrant
            elif self.current_quadrant == quadrant:
                if ct.get_move_cooldown() == 0 and ct.get_action_cooldown() == 0:
                    self.ticks_in_quadrant += 1
                    if self.ticks_in_quadrant > 150:
                        candidates = [(0,0), (0,1), (1,0), (1,1)]
                        candidates.remove(quadrant)
                        new_q = random.choice(candidates)
                        target_x = new_q[0] * cx + cx // 2
                        target_y = new_q[1] * cy + cy // 2
                        target_pos = Position(int(target_x), int(target_y))
                        new_dir = my_pos.direction_to(target_pos)
                        if new_dir != Direction.CENTRE:
                            print(f"[{ct.get_id()}] Context Aware: Leaping from {quadrant} to {new_q}. Dir: {new_dir.name}", file=sys.stderr)
                            self.spawn_direction = new_dir
                            self.current_quadrant = new_q
                            self.ticks_in_quadrant = 0
                            self._resample_heading(ct)
            else:
                self.current_quadrant = quadrant
                self.ticks_in_quadrant = 0

        # 0.5 Aggressive Sabotage Logic (enemy detection + attack)
        # Check this BEFORE Bug2 navigation so we can break out for attacks
        if self._try_opportunistic_gunner(ct):
            return
        if self._aggressive_sabotage(ct):
            return

        # -1. Bug2 Navigation Intercept
        if self.navigation_mode.startswith("BUG2"):
            if getattr(self, 'bug2_target_pos', None) is None:
                self.bug2_target_pos = self.core_pos

            dist_to_target = my_pos.distance_squared(self.bug2_target_pos)
            threshold = getattr(self, 'bug2_target_threshold', 8)

            if dist_to_target <= threshold:
                print(f"[{ct.get_id()}] BUG2: Arrived near target {self.bug2_target_pos}.", file=sys.stderr)
                self.navigation_mode = "EXPLORE"
            else:
                self._bug2_step(ct, self.bug2_target_pos)
                    
            return

        # 0. Stuck detection (Tiered)
        # We check at the START so that early returns from tasks don't bypass counter
        if self.prev_pos is not None and self.prev_pos == my_pos:
            # ONLY increment if we are not on cooldown (if we are on cooldown, we aren't 'stuck', just waiting)
            if ct.get_move_cooldown() == 0 and ct.get_action_cooldown() == 0:
                self.stuck_counter += 1
                if self.stuck_counter >= 5: # Hard bounce (USER requested 5)
                    # Collect valid bounce directions: backward diagonals or sides, NEVER exact opposite
                    valid_bounce_dirs = []
                    for d in DIRECTIONS:
                        if dir_dot(d, self.spawn_direction) <= 0 and d != self.spawn_direction.opposite():
                            valid_bounce_dirs.append(d)
                    
                    if valid_bounce_dirs:
                        new_dir = random.choice(valid_bounce_dirs)
                    else:
                        new_dir = reflect_direction(self.spawn_direction, ct, my_pos)
                    
                    print(f"[{ct.get_id()}] BOUNCE: {self.spawn_direction.name} -> {new_dir.name}", file=sys.stderr)
                        
                    self.spawn_direction = new_dir
                    self.stuck_counter = 0
                    self._resample_heading(ct)
                elif self.stuck_counter >= 3: # Soft resample
                    self.steps_on_heading += 1
                    self._resample_heading(ct)
        else:
            self.stuck_counter = 0
        self.prev_pos = my_pos
        
        # 0.5 Aggressive Sabotage Logic (enemy detection + attack)
        # MOVED ABOVE BUG2 INTERCEPT
        
        # 1. Process forced setup tasks (like elbows, chain links, defensive turrets)
        if len(self.tasks) > 0:
            if ct.get_action_cooldown() == 0:
                task = self.tasks[0]
                task_type = task[0]
                if task_type == "conveyor":
                    pos, direction = task[1], task[2]
                    if ct.can_build_conveyor(pos, direction):
                        ct.build_conveyor(pos, direction)
                        self.conveyor_budget -= 1
                    self.tasks.pop(0)
                else:
                    self.tasks.pop(0)  # Unknown task, discard
            return # Always return if tasks are pending

        # 1.5 Ore scanning — look for ore tiles in vision
        if self.target_ore_pos is None:
            nearby_tiles = ct.get_nearby_tiles()
            best_ore = None
            best_dist = 9999
            for tile_pos in nearby_tiles:
                try:
                    env = ct.get_tile_env(tile_pos)
                    if env == Environment.ORE_TITANIUM:
                        # Skip if a harvester is already built on this ore
                        if ct.get_tile_building_id(tile_pos) is not None:
                            continue
                        dist = (tile_pos.x - my_pos.x)**2 + (tile_pos.y - my_pos.y)**2
                        if dist < best_dist:
                            best_dist = dist
                            best_ore = tile_pos
                except Exception:
                    pass
            if best_ore is not None:
                self.target_ore_pos = best_ore
                ct.draw_indicator_dot(best_ore, 255, 255, 0)  # Yellow dot on ore
        
        # 1.6 Ore approach — try to place harvester if adjacent
        if self.target_ore_pos is not None:
            # Abandon if someone else already built a harvester here
            try:
                if ct.get_tile_building_id(self.target_ore_pos) is not None:
                    self.target_ore_pos = None  # Already claimed, resume exploration
            except Exception:
                self.target_ore_pos = None
        
        if self.target_ore_pos is not None:
            dx_ore = self.target_ore_pos.x - my_pos.x
            dy_ore = self.target_ore_pos.y - my_pos.y
            dist_sq = dx_ore**2 + dy_ore**2
            
            if dist_sq <= 2:  # Adjacent (including diagonal)
                if ct.get_action_cooldown() == 0:
                    if ct.can_build_harvester(self.target_ore_pos):
                        ct.build_harvester(self.target_ore_pos)
                        print(f"[{ct.get_id()}] Placed harvester at {self.target_ore_pos}", file=sys.stderr)
                        # Queue defensive turret (1 per harvester)
                        # Link harvester to the network via conveyor
                        link_dir = my_pos.direction_to(self.target_ore_pos).opposite()
                        if ct.can_move(link_dir):
                            ct.move(link_dir)
                            self.tasks.append(("conveyor", my_pos, link_dir))
                        else:
                            # Fallback if blocked
                            self.tasks.append(("conveyor", my_pos, link_dir))
                            
                        self.target_ore_pos = None
                    # else: Can't afford — wait here patiently, don't abandon
                return
            else:
                # Draw a red line towards ore target
                ct.draw_indicator_line(my_pos, self.target_ore_pos, 255, 0, 0)

        # 2. Scout extension strategy for normal movement
        if self.target_ore_pos is not None:
            # Override heading to walk towards ore
            step_dir = my_pos.direction_to(self.target_ore_pos)
        elif self.target_ore_pos is None:
            step_dir = self.heading
        
        if self.target_ore_pos is None and self.mode == "builder" and step_dir != self.spawn_direction and dir_dot(step_dir, self.spawn_direction) != 2:
            dx, dy = DIR_VECTORS[step_dir]
            choices = []
            if dx > 0: choices.append(Direction.EAST)
            elif dx < 0: choices.append(Direction.WEST)
            if dy > 0: choices.append(Direction.SOUTH)
            elif dy < 0: choices.append(Direction.NORTH)
            
            step_dir = choices[self.steps_on_heading % len(choices)] if len(choices) > 0 else step_dir

        elif self.target_ore_pos is None:
            step_dir = self.get_orthogonal_step()

        # Candidate rotation loop
        candidate = step_dir
        map_w = ct.get_map_width()
        map_h = ct.get_map_height()
        
        valid_candidates = []
        c = step_dir
        for _ in range(7):
            target_pos = my_pos.add(c)
            
            # Bounds check
            if target_pos.x < 0 or target_pos.x >= map_w or target_pos.y < 0 or target_pos.y >= map_h:
                c = c.rotate_right()
                continue
                
            # Don't try backward directions (unless approaching ore)
            if self.target_ore_pos is None and is_backward(c, self.spawn_direction):
                c = c.rotate_right()
                continue
                
            try:
                env = ct.get_tile_env(target_pos)
                if env != Environment.EMPTY: # E.g Wall or Ore
                    c = c.rotate_right()
                    continue
            except Exception:
                c = c.rotate_right()
                continue

            # Skip tiles with non-walkable buildings (turrets, etc.)
            try:
                occ_id = ct.get_tile_building_id(target_pos)
                if occ_id is not None:
                    occ_type = ct.get_entity_type(occ_id)
                    occ_team = ct.get_team(occ_id)
                    # If confirmed core, we CAN walk on ENEMY conveyors and ROADS
                    is_traversable_enemy_structure = (occ_team != ct.get_team() and occ_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.ROAD))
                    
                    if not is_traversable_enemy_structure:
                        if occ_type in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH,
                                        EntityType.HARVESTER, EntityType.FOUNDRY, EntityType.CORE,
                                        EntityType.LAUNCHER):
                            c = c.rotate_right()
                            continue
            except Exception:
                pass
                
            # If we need a conveyor, ensure we can actually build it before committing
            # EXCEPT if we are stepping onto an enemy conveyor for sabotage
            if not ct.is_tile_passable(target_pos) and ct.get_action_cooldown() == 0:
                # Check again for enemy conveyor
                is_traversable_enemy_structure = False
                try:
                    occ_id = ct.get_tile_building_id(target_pos)
                    if occ_id is not None and ct.get_team(occ_id) != ct.get_team():
                        if ct.get_entity_type(occ_id) in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.ROAD):
                            is_traversable_enemy_structure = True
                except Exception:
                    pass

                if not is_traversable_enemy_structure:
                    build_dir = c.opposite()
                    if not ct.can_build_conveyor(target_pos, build_dir):
                        c = c.rotate_right()
                        continue
                
            valid_candidates.append(c)
            c = c.rotate_right()
            
        # Pick the best valid candidate. Prioritize friendly conveyors to avoid parallel builds.
        best_candidate = None
        if valid_candidates:
            if self.target_ore_pos is None:
                my_team = ct.get_team()
                for cand in valid_candidates:
                    t_pos = my_pos.add(cand)
                    try:
                        b_id = ct.get_tile_building_id(t_pos)
                        if b_id is not None and ct.get_team(b_id) == my_team and ct.get_entity_type(b_id) == EntityType.CONVEYOR:
                            best_candidate = cand
                            break
                    except Exception:
                        pass
            if best_candidate is None:
                best_candidate = valid_candidates[0]
                
        candidate = best_candidate if best_candidate is not None else step_dir
            
        target_pos = my_pos.add(candidate)
        ct.draw_indicator_line(my_pos, target_pos, 0, 255, 0)
        
        if not ct.is_tile_passable(target_pos):
            if (self.target_ore_pos is not None) or (self.conveyor_budget > 0):
                # Budget guardrail: don't build conveyors if it would starve harvesters
                harv_cost = ct.get_harvester_cost()[0]
                conv_cost = ct.get_conveyor_cost()[0]
                safety_floor = harv_cost + 3 * conv_cost
                titanium = ct.get_global_resources()[0]
                if titanium < safety_floor and self.target_ore_pos is None:
                    return  # Save titanium for harvesters
                build_dir = candidate.opposite()
                if ct.can_build_conveyor(target_pos, build_dir):
                    ct.build_conveyor(target_pos, build_dir)
                    self.conveyor_budget -= 1
            return

        # 3. Step forward
        if ct.get_move_cooldown() == 0:
            if ct.can_move(candidate):
                ct.move(candidate)
                self.stuck_counter = 0 # Reset on successful move
                self.steps_on_heading += 1
                self.steps_since_resample -= 1
                
                if self.steps_since_resample <= 0:
                    self._resample_heading(ct)
                
        # Check if we need to pave our vacated tile to connect the chain
        if self.vacated_task is not None:
            self.tasks.append(self.vacated_task)
            self.vacated_task = None
        
        # Queue paving on the tile we just left (for ore approach or normal movement)
        new_pos = ct.get_position()
        if my_pos != new_pos:
            pave_dir = my_pos.direction_to(new_pos)  # Points forward (we want backward)
            under_limit = getattr(self, 'local_coverage', 0) < 0.70
            
            if (self.target_ore_pos is not None) or (self.conveyor_budget > 0 and under_limit):
                # Budget guardrail: skip paving if titanium is low
                harv_cost = ct.get_harvester_cost()[0]
                conv_cost = ct.get_conveyor_cost()[0]
                safety_floor = harv_cost + 3 * conv_cost
                titanium = ct.get_global_resources()[0]
                if titanium >= safety_floor or self.target_ore_pos is not None:
                    # Build conveyor pointing backwards (towards core)
                    self.vacated_task = ("conveyor", my_pos, pave_dir.opposite())
            self.last_built_pos = my_pos
