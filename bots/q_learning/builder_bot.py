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
        
        # 1. Process forced setup tasks (like elbows)
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
                    if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
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
                
            # Don't try backward directions
            if is_backward(candidate, self.spawn_direction):
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
                self.steps_on_heading += 1
                self.steps_since_resample -= 1
                
                if self.steps_since_resample <= 0:
                    self._resample_heading(ct)
                
                # Check if we need to pave our vacated tile to connect the chain
                if self.vacated_task is not None:
                    self.tasks.append(self.vacated_task)
                    self.vacated_task = None
                
        # 4. Stuck detection
        new_pos = ct.get_position()
        if self.prev_pos is not None and self.prev_pos == new_pos:
            self.stuck_counter += 1
            if self.stuck_counter >= 5: # Stuck threshold
                self.steps_on_heading += 1 # Resample orthogonal direction manually to break symmetry sometimes
                self._resample_heading(ct)
                self.stuck_counter = 0
        else:
            self.stuck_counter = 0
        self.prev_pos = new_pos
