import sys
import math
import random
from cambc import Controller, Direction, EntityType, Environment

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
        self.conveyor_budget = 15
        
        # New movement logic
        self.tasks = []
        self.vacated_task = None
        self.steps_on_heading = 0
        self.prev_pos = None
        self.stuck_counter = 0
        self.steps_since_resample = 0
        self.target_ore_pos = None
        self.last_built_pos = None  # Tail of our conveyor chain

    def get_orthogonal_step(self):
        dx, dy = DIR_VECTORS[self.spawn_direction]
        choices = []
        if dx > 0: choices.append(Direction.EAST)
        elif dx < 0: choices.append(Direction.WEST)
        if dy > 0: choices.append(Direction.SOUTH)
        elif dy < 0: choices.append(Direction.NORTH)
        
        if len(choices) == 1:
            return choices[0]
        else:
            return choices[self.steps_on_heading % 2]

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
        units = ct.get_nearby_units()
        local_density = len(buildings) + len(units) # Rough density metric
        
        # 2. Compute variance
        max_variance = 2.0
        density_scale = max_variance / (1 + (local_density * 0.5))
        
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

        # 0. Stuck detection (Tiered)
        # We check at the START so that early returns from tasks don't bypass counter
        if self.prev_pos is not None and self.prev_pos == my_pos:
            # ONLY increment if we are not on cooldown (if we are on cooldown, we aren't 'stuck', just waiting)
            if ct.get_move_cooldown() == 0 and ct.get_action_cooldown() == 0:
                self.stuck_counter += 1
                if self.stuck_counter >= 5: # Hard bounce (USER requested 5)
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
        
        # 0.5 Enemy Sabotage Logic
        enemy_buildings = ct.get_nearby_buildings()
        target_sabotage_pos = None
        for b_id in enemy_buildings:
            if ct.get_team(b_id) != ct.get_team():
                b_type = ct.get_entity_type(b_id)
                # Prioritize infrastructure that we can effectively destroy
                if b_type in (EntityType.CONVEYOR, EntityType.ROAD, EntityType.BRIDGE, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR):
                    b_pos = ct.get_position(b_id)
                    # If we are ON the enemy building, BOOM
                    if b_pos == my_pos:
                        print(f"[{ct.get_id()}] SABOTAGE: On enemy {b_type.value} at {b_pos}. Self-destructing!", file=sys.stderr)
                        ct.self_destruct()
                        return
                    
                    # Otherwise, prioritize the closest one
                    if target_sabotage_pos is None:
                        target_sabotage_pos = b_pos
                    else:
                        dist_new = my_pos.distance_squared(b_pos)
                        dist_old = my_pos.distance_squared(target_sabotage_pos)
                        if dist_new < dist_old:
                            target_sabotage_pos = b_pos

        if target_sabotage_pos is not None:
            ct.draw_indicator_line(my_pos, target_sabotage_pos, 255, 165, 0) # Orange line for sabotage
            ct.draw_indicator_dot(target_sabotage_pos, 255, 0, 0) # Red dot on target
            
            sabotage_dir = my_pos.direction_to(target_sabotage_pos)
            if ct.get_move_cooldown() == 0:
                # Try to move directly to the target
                if ct.can_move(sabotage_dir):
                    ct.move(sabotage_dir)
                    return
                else:
                    # If blocked, try to rotate slightly towards it
                    for d in [sabotage_dir.rotate_left(), sabotage_dir.rotate_right()]:
                        if ct.can_move(d):
                            ct.move(d)
                            return
        
        # 1. Process forced setup tasks (like elbows, chain links)
        if len(self.tasks) > 0:
            task = self.tasks[0]
            task_type, pos, direction = task
            if ct.get_action_cooldown() == 0:
                if task_type == "conveyor":
                    if ct.can_build_conveyor(pos, direction):
                        ct.build_conveyor(pos, direction)
                        self.conveyor_budget -= 1
                        if self.conveyor_budget <= 0:
                            self.mode = "scout"
                elif task_type == "road":
                    if ct.can_build_road(pos):
                        ct.build_road(pos)
                self.tasks.pop(0)
            return

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
                        # Queue a conveyor on our current tile pointing towards the harvester
                        # This links the chain to the harvester
                        link_dir = my_pos.direction_to(self.target_ore_pos)
                        if self.mode == "builder" and self.conveyor_budget > 0:
                            self.tasks.append(("conveyor", my_pos, link_dir))
                        else:
                            self.tasks.append(("road", my_pos, None))
                    self.target_ore_pos = None  # Clear regardless
                return
            else:
                # Draw a red line towards ore target
                ct.draw_indicator_line(my_pos, self.target_ore_pos, 255, 0, 0)

        # 2. Scout extension strategy for normal movement
        if self.target_ore_pos is not None:
            # Override heading to walk towards ore
            step_dir = my_pos.direction_to(self.target_ore_pos)
        elif self.mode == "scout":
            step_dir = self.spawn_direction
        else:
            step_dir = self.heading
        
        if self.target_ore_pos is None and self.mode == "builder" and step_dir != self.spawn_direction and dir_dot(step_dir, self.spawn_direction) != 2:
            dx, dy = DIR_VECTORS[step_dir]
            choices = []
            if dx > 0: choices.append(Direction.EAST)
            elif dx < 0: choices.append(Direction.WEST)
            if dy > 0: choices.append(Direction.SOUTH)
            elif dy < 0: choices.append(Direction.NORTH)
            
            step_dir = choices[self.steps_on_heading % len(choices)] if len(choices) > 0 else step_dir

        elif self.target_ore_pos is None and self.mode == "builder":
            step_dir = self.get_orthogonal_step()

        # Candidate rotation loop
        candidate = step_dir
        map_w = ct.get_map_width()
        map_h = ct.get_map_height()
        
        for _ in range(7):
            target_pos = my_pos.add(candidate)
            
            # Bounds check
            if target_pos.x < 0 or target_pos.x >= map_w or target_pos.y < 0 or target_pos.y >= map_h:
                candidate = candidate.rotate_right()
                continue
                
            # Don't try backward directions (unless approaching ore)
            if self.target_ore_pos is None and is_backward(candidate, self.spawn_direction):
                candidate = candidate.rotate_right()
                continue
                
            try:
                env = ct.get_tile_env(target_pos)
                if env != Environment.EMPTY: # E.g Wall or Ore
                    candidate = candidate.rotate_right()
                    continue
            except Exception:
                candidate = candidate.rotate_right()
                continue
                
            # If we need a conveyor, ensure we can actually build it before committing
            if not ct.is_tile_passable(target_pos) and ct.get_action_cooldown() == 0 and self.mode == "builder":
                build_dir = candidate.opposite()
                if not ct.can_build_conveyor(target_pos, build_dir):
                    candidate = candidate.rotate_right()
                    continue
                
            break
            
        target_pos = my_pos.add(candidate)
        ct.draw_indicator_line(my_pos, target_pos, 0, 255, 0)
        
        if not ct.is_tile_passable(target_pos):
            if ct.get_action_cooldown() == 0:
                if self.mode == "builder":
                    build_dir = candidate.opposite()
                    if ct.can_build_conveyor(target_pos, build_dir):
                        ct.build_conveyor(target_pos, build_dir)
                        self.conveyor_budget -= 1
                        if self.conveyor_budget <= 0:
                            self.mode = "scout"
                    elif self.conveyor_budget <= 0:
                        self.mode = "scout"
                elif self.mode == "scout":
                    if ct.can_build_road(target_pos):
                        ct.build_road(target_pos)
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
            if self.mode == "builder" and self.conveyor_budget > 0:
                # Build conveyor pointing backwards (towards core)
                self.vacated_task = ("conveyor", my_pos, pave_dir.opposite())
            elif self.mode == "scout":
                self.vacated_task = ("road", my_pos, None)
            self.last_built_pos = my_pos
