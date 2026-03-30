import array
from collections import deque
from enum import Enum, EnumType
import heapq
from sys import stderr

from cambc import Controller, Direction, EntityType, Position, Team, Environment

class LUT(Enum):
    UNEXPLORED = 0
    EMPTY = 1
    ORE_TITANIUM = 2
    WALL = 3
    ORE_AXIONITE = 4

class SymmetryAnalyzer:
    def __init__(self, w: int, h: int, ally_core_pos: Position):
        self.w = w
        self.h = h
        self.ally_core_pos = ally_core_pos
        self.map_lut = [LUT.UNEXPLORED] * (w * h)
        self.possible_symmetries = ["horizontal", "vertical", "rotational"]
        self.eliminate_core_overlap()

    def _get_idx(self, x: int, y: int) -> int:
        return y * self.w + x

    def eliminate_core_overlap(self):
        """Early elimination based on core position overlap."""
        cx, cy = self.ally_core_pos.x, self.ally_core_pos.y
        overlap_x = abs(2 * cx - (self.w - 1)) <= 2
        overlap_y = abs(2 * cy - (self.h - 1)) <= 2
        
        if overlap_x and "horizontal" in self.possible_symmetries:
            self.possible_symmetries.remove("horizontal")
        if overlap_y and "vertical" in self.possible_symmetries:
            self.possible_symmetries.remove("vertical")
        if overlap_x and overlap_y and "rotational" in self.possible_symmetries:
            self.possible_symmetries.remove("rotational")

    def update_symmetry(self, ct: Controller, nearby_tiles: list[Position], nearby_units: list[int]):
        cx, cy = self.ally_core_pos.x, self.ally_core_pos.y
        
        # 1. Deterministic Core-based Symmetry Confirmation
        enemy_id = 2 if ct.get_team() == Team.A else 1
        if enemy_id in nearby_units:
            enemy_pos = ct.get_position(enemy_id)
            ex, ey = enemy_pos.x, enemy_pos.y
            
            confirmed_sym = None
            if ex == self.w - 1 - cx and ey == cy:
                confirmed_sym = "horizontal"
            elif ex == cx and ey == self.h - 1 - cy:
                confirmed_sym = "vertical"
            elif ex == self.w - 1 - cx and ey == self.h - 1 - cy:
                confirmed_sym = "rotational"
            
            if confirmed_sym and confirmed_sym in self.possible_symmetries:
                self.possible_symmetries = [confirmed_sym]
                return # Core found, symmetry is deterministic
        
        # 2. Environment-based POI Matching (if not yet deterministic)
        if len(self.possible_symmetries) <= 1:
            return

        for pos in nearby_tiles:
            idx = self._get_idx(pos.x, pos.y)
            if self.map_lut[idx] != LUT.UNEXPLORED:
                continue
                
            env = ct.get_tile_env(pos)
            if env == Environment.ORE_TITANIUM:
                val = LUT.ORE_TITANIUM
            elif env == Environment.WALL:
                val = LUT.WALL
            elif env == Environment.ORE_AXIONITE:
                val = LUT.ORE_AXIONITE
            else:
                val = LUT.EMPTY

            for sym in self.possible_symmetries[:]:
                sym_x, sym_y = pos.x, pos.y
                if sym == "horizontal":
                    sym_x = self.w - 1 - pos.x
                elif sym == "vertical":
                    sym_y = self.h - 1 - pos.y
                elif sym == "rotational":
                    sym_x = self.w - 1 - pos.x
                    sym_y = self.h - 1 - pos.y

                if 0 <= sym_x < self.w and 0 <= sym_y < self.h:
                    sym_idx = self._get_idx(sym_x, sym_y)
                    sym_val = self.map_lut[sym_idx]
                    if sym_val != LUT.UNEXPLORED and sym_val != val:
                        self.possible_symmetries.remove(sym)

            self.map_lut[idx] = val

    def draw_debug(self, ct: Controller):
        current_pos = ct.get_position()
        cx, cy = self.ally_core_pos.x, self.ally_core_pos.y
        for sym in self.possible_symmetries:
            if sym == "horizontal":
                ct.draw_indicator_line(current_pos, Position(self.w - 1 - cx, cy), 255, 165, 0)
            elif sym == "vertical":
                ct.draw_indicator_line(current_pos, Position(cx, self.h - 1 - cy), 255, 165, 0)
            elif sym == "rotational":
                ct.draw_indicator_line(current_pos, Position(self.w - 1 - cx, self.h - 1 - cy), 255, 165, 0)
                

CARDINALS = [
    Direction.NORTH,
    Direction.SOUTH,
    Direction.EAST,
    Direction.WEST
]
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

DELTAS = [ (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), ]
REVERSE_DIR_CODES = [(i + 4) % len(DELTAS) for i in range(len(DELTAS))]
DELTA_TO_DIRECTION = {direction.delta(): direction for direction in DIRECTIONS}
DIR_CODE_TO_DIRECTION = [DELTA_TO_DIRECTION[delta] for delta in DELTAS]

class Navigation:
    def __init__(self,w,h):
        self.w = w
        self.h = h
        self.map_lut = [[0]*h for _ in range(w)]
        self.current_pos: Position | None = None

        self.pq = []

        self.last_target = None
        self.visited = set()
        
        self.bucket_n = self.w * self.h
        self.min_ptr = 0
        self.max_ptr = 0
        self.inserted_items = 0
        self.buckets = [[] for _ in range(self.bucket_n)]
        self.open_pos = set()
        self.parent_dir = array.array("b", [-1]) * self.bucket_n
        self.parent_epoch = array.array("I", [0]) * self.bucket_n
        self.next_dir = array.array("b", [-1]) * self.bucket_n
        self.next_epoch = array.array("I", [0]) * self.bucket_n
        self.search_epoch = 0
        self.route_epoch = 0
        self.max_a_star_expansions = 64
        self.max_a_star_frontier = 32
    
    def _get_idx(self, x: int, y: int) -> int:
        return y * self.w + x
    
    def in_bounds(self,x:int,y:int):
        return 0 <= x < self.w and 0 <= y < self.h

    def _begin_search(self):
        self.search_epoch += 1
        self.route_epoch = 0
        return self.search_epoch

    def _invalidate_route(self):
        self.route_epoch = 0

    def _step_idx(self, idx: int, dir_code: int) -> int:
        x = idx % self.w
        y = idx // self.w
        dx, dy = DELTAS[dir_code]
        return self._get_idx(x + dx, y + dy)

    def _rebuild_route(self, start_idx: int, stopped_idx: int, search_epoch: int):
        if stopped_idx == start_idx:
            self._invalidate_route()
            return

        self.route_epoch = search_epoch
        current_idx = stopped_idx
        while current_idx != start_idx and self.parent_epoch[current_idx] == search_epoch:
            reverse_dir = self.parent_dir[current_idx]
            if reverse_dir < 0:
                break
            parent_idx = self._step_idx(current_idx, reverse_dir)
            self.next_dir[parent_idx] = REVERSE_DIR_CODES[reverse_dir]
            self.next_epoch[parent_idx] = self.route_epoch
            current_idx = parent_idx

        if current_idx != start_idx:
            self._invalidate_route()

    def _has_route_step(self, idx: int) -> bool:
        return self.route_epoch != 0 and self.next_epoch[idx] == self.route_epoch and self.next_dir[idx] >= 0

    def _heuristic(self, x: int, y: int, target_pos: Position) -> int:
        return max(abs(x - target_pos.x), abs(y - target_pos.y))

    def _pick_better_fallback(
        self,
        current_best: tuple[int, int, int, tuple[int, int]] | None,
        node: tuple[int, int],
        g_cost: int,
        target_pos: Position,
    ):
        heuristic = self._heuristic(node[0], node[1], target_pos)
        score = (heuristic, g_cost + heuristic, g_cost, node)
        if current_best is None or score < current_best:
            return score
        return current_best

    def update_info(self,ct:Controller,current_pos:Position,nearby_tiles:list[Position],nearby_buildings:list[int]):
        self.current_pos = current_pos
        # Update LUT
        for pos in nearby_tiles:
            x,y = pos
            tile_env = ct.get_tile_env(pos)
            match tile_env:
                case Environment.EMPTY:
                    self.map_lut[x][y] = 1
                case Environment.ORE_TITANIUM:
                    self.map_lut[x][y] = 2
                case Environment.ORE_AXIONITE:
                    self.map_lut[x][y] = 3
                case Environment.WALL:
                    self.map_lut[x][y] = 4

        for building in nearby_buildings:
            pos = ct.get_position(building)
            x,y = pos
            btype = ct.get_entity_type(building)
            match btype:
                case EntityType.CORE:
                    team = ct.get_team(building) == ct.get_team()
                    if team:
                        continue
                    self.map_lut[x][y] = 5
                    for direction in DIRECTIONS:
                        x,y = pos.add(direction)
                        self.map_lut[x][y] = 5
                case EntityType.HARVESTER:
                    self.map_lut[x][y] = 6

    def reset_pq(self):
        self.min_ptr = self.bucket_n
        self.max_ptr = 0
        self.inserted_items = 0
        while self.open_pos:
            top = self.open_pos.pop()
            self.buckets[top] = []
    
    def push_pq(self,rank,item):
        self.open_pos.add(rank)
        self.buckets[rank].append(item)

        if rank < self.min_ptr: # Pick min
            self.min_ptr = rank
        
        if rank > self.max_ptr:
            self.max_ptr = rank

        self.inserted_items += 1
    
    def pop_pq(self):
        while not self.buckets[self.min_ptr]:
            self.min_ptr+=1
        top_item = self.buckets[self.min_ptr].pop()
        if len(self.buckets[self.min_ptr]) == 0:
            self.open_pos.remove(self.min_ptr)
        self.inserted_items -= 1
        return ( self.min_ptr,top_item )         

    def pop_worst_pq(self):
        while self.max_ptr > 0 and not self.buckets[self.max_ptr]:
            self.max_ptr -= 1

        if not self.buckets[self.max_ptr]:
            return None

        top_item = self.buckets[self.max_ptr].pop()
        if len(self.buckets[self.max_ptr]) == 0:
            self.open_pos.remove(self.max_ptr)
            while self.max_ptr > 0 and not self.buckets[self.max_ptr]:
                self.max_ptr -= 1
        self.inserted_items -= 1
        return (self.max_ptr, top_item)
    
    def a_star(self,target_pos:Position):
        self.reset_pq()
        start = (self.current_pos.x,self.current_pos.y)
        start_idx = self._get_idx(*start)
        search_epoch = self._begin_search()
        self.push_pq(0,start)

        check = [-1] * (self.w * self.h)
        check[start_idx] = 0

        stopped_at = (target_pos.x,target_pos.y)
        while self.open_pos:
            top = self.pop_pq()
            reached_target = top[1] == stopped_at
            goes_into_unknown = self.map_lut[top[1][0]][top[1][1]] == 0
            if reached_target or goes_into_unknown:
                stopped_at = top[1]
                break
            elapsed_dist = check[self._get_idx(*top[1])]
            for dir_code, deltas in enumerate(DELTAS):
                neighbor = ( top[1][0] + deltas[0],top[1][1] + deltas[1] )
                if not (0 <= neighbor[0] < self.w and 0 <= neighbor[1] < self.h ) or self.map_lut[neighbor[0]][neighbor[1]] >= 4:
                    continue
                new_dist = 1 + elapsed_dist

                neighbor_idx = self._get_idx(*neighbor)
                neighbor_dist = check[neighbor_idx]
                if neighbor_dist == -1 or new_dist < neighbor_dist:
                    check[neighbor_idx] = new_dist
                    self.parent_dir[neighbor_idx] = REVERSE_DIR_CODES[dir_code]
                    self.parent_epoch[neighbor_idx] = search_epoch
                    rank = new_dist + self._heuristic(neighbor[0], neighbor[1], target_pos)
                    self.push_pq(rank,neighbor)
        self._rebuild_route(start_idx, self._get_idx(*stopped_at), search_epoch)

    def a_star_limited(
        self,
        target_pos: Position,
        max_expansions: int | None = None,
        max_frontier_size: int | None = None,
    ):
        self.reset_pq()
        start = (self.current_pos.x, self.current_pos.y)
        start_idx = self._get_idx(*start)
        search_epoch = self._begin_search()
        check = [-1] * (self.w * self.h)
        check[start_idx] = 0
        stopped_at = start
        best_fallback = self._pick_better_fallback(None, start, 0, target_pos)
        expansions = 0
        expansion_budget = self.max_a_star_expansions if max_expansions is None else max_expansions
        frontier_limit = self.max_a_star_frontier if max_frontier_size is None else max_frontier_size
        self.push_pq(0, start)

        while self.open_pos and expansions < expansion_budget:
            _, node = self.pop_pq()
            expansions += 1

            reached_target = node == (target_pos.x, target_pos.y)
            goes_into_unknown = self.map_lut[node[0]][node[1]] == 0
            if reached_target or goes_into_unknown:
                stopped_at = node
                break

            elapsed_dist = check[self._get_idx(*node)]
            best_fallback = self._pick_better_fallback(best_fallback, node, elapsed_dist, target_pos)
            for dir_code, deltas in enumerate(DELTAS):
                neighbor = (node[0] + deltas[0], node[1] + deltas[1])
                if not self.in_bounds(*neighbor) or self.map_lut[neighbor[0]][neighbor[1]] >= 4:
                    continue

                new_dist = elapsed_dist + 1
                neighbor_idx = self._get_idx(*neighbor)
                neighbor_dist = check[neighbor_idx]
                if neighbor_dist != -1 and new_dist >= neighbor_dist:
                    continue

                check[neighbor_idx] = new_dist
                self.parent_dir[neighbor_idx] = REVERSE_DIR_CODES[dir_code]
                self.parent_epoch[neighbor_idx] = search_epoch
                rank = new_dist + self._heuristic(neighbor[0], neighbor[1], target_pos)
                self.push_pq(rank, neighbor)
                best_fallback = self._pick_better_fallback(best_fallback, neighbor, new_dist, target_pos)
                if self.inserted_items > frontier_limit:
                    self.pop_worst_pq()
        else:
            if best_fallback is not None:
                stopped_at = best_fallback[3]

        self._rebuild_route(start_idx, self._get_idx(*stopped_at), search_epoch)

    def a_star_cutoff(self, target_pos: Position, max_expansions: int | None = None):
        self.a_star_limited(target_pos, max_expansions=max_expansions)

    def a_star_bounded_frontier(self, target_pos: Position, max_frontier_size: int | None = None):
        self.a_star_limited(target_pos, max_frontier_size=max_frontier_size)

    def move(self,ct:Controller,target_pos:Position):
        self.current_pos = ct.get_position()
        current_idx = self._get_idx(self.current_pos.x, self.current_pos.y)
        if self.last_target != target_pos or not self._has_route_step(current_idx):
            self.last_target = target_pos
            self.a_star_limited(target_pos)
            # self.a_star(target_pos)
        if not self._has_route_step(current_idx):
            return False

        direction = DIR_CODE_TO_DIRECTION[self.next_dir[current_idx]]
        next_pos = self.current_pos.add(direction)
        can_move = ct.can_move(direction) or ct.can_build_road(next_pos)
        if not can_move:
            self._invalidate_route()
            self.a_star_limited(target_pos)
            # self.a_star(target_pos)
            current_idx = self._get_idx(self.current_pos.x, self.current_pos.y)
            if not self._has_route_step(current_idx):
                return False
            direction = DIR_CODE_TO_DIRECTION[self.next_dir[current_idx]]
            next_pos = self.current_pos.add(direction)

        if ct.can_move(direction):
            ct.move(direction)
            return True
        elif ct.can_build_road(next_pos):
            ct.build_road(next_pos)
            ct.move(direction)
            return True

    def get_neighbors(self,root_pos=None):
        start_pos = self.current_pos
        if root_pos:
            start_pos = root_pos
        quads = [
            (start_pos.x, start_pos.y - 5),
            (start_pos.x + 5, start_pos.y - 5),
            (start_pos.x + 5, start_pos.y),
            (start_pos.x + 5, start_pos.y + 5),
            (start_pos.x, start_pos.y + 5),
            (start_pos.x - 5, start_pos.y + 5),
            (start_pos.x - 5, start_pos.y),
            (start_pos.x - 5, start_pos.y - 5),
        ]
        neighbors = []
        for q in quads:
            if self.in_bounds(*q) and q not in self.visited:
                neighbors.append((0,q))
                self.visited.add(q)
        return neighbors

    def explore(self,ct:Controller):
        for _,p in self.pq:
            ct.draw_indicator_dot(Position(*p),255,0,0)

        if not self.pq:
            self.pq = self.get_neighbors()

        top = self.pq[0][1]
        if (self.current_pos.x,self.current_pos.y) == top:
            self.pq.pop(0)
            self.pq.extend(self.get_neighbors())
        elif self.map_lut[top[0]][top[1]] >= 4: # Impassible
            self.pq.pop(0)
        
        # Update distances
        new_pq = []
        for i in range(len(self.pq)):
            _,pos = self.pq[i]
            new_val = max(abs(self.current_pos.x-pos[0]),abs(self.current_pos.y-pos[1]))
            heapq.heappush(new_pq,(new_val,pos))
        self.pq = new_pq
        final_target = Position(*self.pq[0][1])
        ct.draw_indicator_line(self.current_pos,final_target,0,255,0)
        self.move(ct,final_target)
