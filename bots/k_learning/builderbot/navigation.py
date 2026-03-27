from enum import Enum
import heapq
from math import e
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

class Navigation:
    def __init__(self,w,h):
        self.w = w
        self.h = h
        self.map_lut = [0] * (w * h)
        self.quad_scaling = 5
        self.current_pos: Position | None = None
        self.sym = None
        self.pq = []
    
    def _get_idx(self, x: int, y: int) -> int:
        return y * self.w + x
    
    def in_bounds(self,x:int,y:int):
        return 0 <= x < self.w and 0 <= y < self.h

    def update_info(self,ct:Controller,current_pos:Position,nearby_tiles:list[Position],sym:SymmetryAnalyzer):
        self.current_pos = current_pos
        self.sym = sym
        
        # Update LUT
        for pos in nearby_tiles:
            idx = self._get_idx(*pos)
            self.map_lut[idx] = 1
    
    def get_lut(self,x,y):
        return self.map_lut[self._get_idx(x,y)]

    def move(self,ct:Controller,target_pos:Position):
        m_dir = self.current_pos.direction_to(target_pos)
        for _ in range(8):
            next_pos = self.current_pos.add(m_dir)
            if ct.can_move(m_dir) and self.get_lut(*next_pos) == 0:
                ct.move(m_dir)
                return True
            elif ct.can_build_road(next_pos):
                ct.build_road(next_pos)
                ct.move(m_dir)
                return True
            else:
                m_dir = m_dir.rotate_left()
        for _ in range(8):
            next_pos = self.current_pos.add(m_dir)
            if ct.can_move(m_dir):
                ct.move(m_dir)
                return True
            elif ct.can_build_road(next_pos):
                ct.build_road(next_pos)
                ct.move(m_dir)
                return True
            else:
                m_dir = m_dir.rotate_right()
        return False

    def get_neighbors(self):
        quads = [
            (self.current_pos.x, self.current_pos.y - 5),
            (self.current_pos.x + 5, self.current_pos.y - 5),
            (self.current_pos.x + 5, self.current_pos.y),
            (self.current_pos.x + 5, self.current_pos.y + 5),
            (self.current_pos.x, self.current_pos.y + 5),
            (self.current_pos.x - 5, self.current_pos.y + 5),
            (self.current_pos.x - 5, self.current_pos.y),
            (self.current_pos.x - 5, self.current_pos.y - 5),
        ]
        neighbors = []
        for q in quads:
            if self.in_bounds(*q) and self.get_lut(*q) == 0:
                neighbors.append((0,q))
        return neighbors

    def explore(self,ct:Controller):
        for _,p in self.pq:
            ct.draw_indicator_dot(Position(*p),255,0,0)

        if not self.pq:
            self.pq = self.get_neighbors()
            
        
        top = self.pq[0][1]
        if top == self.current_pos or top == ct.get_position():
            self.pq.pop(0)
            self.pq.extend(self.get_neighbors())
            # Update distances
            new_pq = []
            for i in range(len(self.pq)):
                _,pos = self.pq[i]
                new_val = self.current_pos.distance_squared(Position(*pos))
                heapq.heappush(new_pq,(new_val,pos))
            self.pq = new_pq
        elif self.sym.map_lut[self._get_idx(*top)] == LUT.WALL:
            self.pq.pop(0)
        else:
            self.move(ct,Position(*top))