import sys

from collections import deque
from cambc import Controller, Direction, EntityType

DIRECTIONS = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST
]

class Core:
    def __init__(self):
        self.spawned = 0
        self.reinvestment_budget = 0 # Available titanium for spawning
        self.last_titanium = 0
        
        # Adaptive Growth (25-round Sliding Window)
        self.growth_history = deque(maxlen=25)
        self.sum_x = 0
        self.sum_x2 = 0
        self.moving_avg_growth = 0
        self.variance = 0
        
        # Opposite direction index pairs for symmetry: (N,S), (E,W), (NE,SW), (SE,NW)
        self.pairs = [(0, 4), (2, 6), (1, 5), (3, 7)]

        # Resource Drain Wave (Aggressive Spawning Mode)
        self.drain_wave_active = False
        self.drain_wave_rounds_left = 0
        self.DRAIN_WAVE_DURATION = 20  # Spawn every round for 20 rounds

    def run(self, ct: Controller):
        res = ct.get_global_resources()
        titanium = res[0]
        rnd = ct.get_current_round()

        # 0. Growth tracking (25-round Sliding Window)
        if rnd > 0:
            delta = max(0, titanium - self.last_titanium)
            
            # Incremental update logic: subtract old, add new
            if len(self.growth_history) == 25:
                old_x = self.growth_history[0]
                self.sum_x -= old_x
                self.sum_x2 -= old_x**2
            
            self.growth_history.append(delta)
            self.sum_x += delta
            self.sum_x2 += delta**2
            
            count = len(self.growth_history)
            self.moving_avg_growth = self.sum_x / count
            self.variance = max(0, (self.sum_x2 / count) - (self.moving_avg_growth ** 2))
            
            # 0.5. Budget Accrual (Flow Economy)
            # Reinvest 80% of growth if above safety threshold
            if self.moving_avg_growth >= 1.2:
                self.reinvestment_budget += self.moving_avg_growth * 0.8
        
        # 0.6 Signal Scanning — check for ENEMY CORE detection marker
        # Builders will place a DRAN marker when they find the enemy core and return
        marker_found = False
        nearby_entities = ct.get_nearby_entities()
        for e_id in nearby_entities:
            try:
                if ct.get_entity_type(e_id) == EntityType.MARKER:
                    # get_marker_value throws an exception for enemy markers, which is fine to catch and ignore
                    if ct.get_marker_value(e_id) == 0x4452414E:
                        marker_found = True
                        break
            except Exception:
                pass

        if marker_found and not self.drain_wave_active and rnd > 100:
            print(f"[CORE] DRAIN WAVE ACTIVATED! Attack marker detected. "
                  f"Spawning every round for {self.DRAIN_WAVE_DURATION} rounds.",
                  file=sys.stderr)
            self.drain_wave_active = True
            self.drain_wave_rounds_left = self.DRAIN_WAVE_DURATION

        self.last_titanium = titanium

        if ct.get_action_cooldown() == 0:
            # DRAIN WAVE: Aggressive spawning — one bot every round
            # Keep 100 Ti floor so we can still build harvesters
            if self.drain_wave_active:
                if self.drain_wave_rounds_left > 0 and titanium >= 100:
                    print(f"[CORE] DRAIN WAVE SPAWN "
                          f"({self.drain_wave_rounds_left} left, Ti={titanium})",
                          file=sys.stderr)
                    self._spawn(ct)
                    self.drain_wave_rounds_left -= 1
                elif self.drain_wave_rounds_left <= 0:
                    print("[CORE] DRAIN WAVE ENDED.", file=sys.stderr)
                    self.drain_wave_active = False
                return

            # 1. Opening Sequence (Max 4 bots initially)
            if rnd < 60:
                if self.spawned < 4 and titanium >= 20:
                    self._spawn(ct)
                return

            # 2. Flow Reinvestment: Spawn if budget allows (Cost per bot ~132)
            if self.reinvestment_budget >= 132 and titanium >= 20:
                print(f"[Core] Flow Spawn. Budget: {self.reinvestment_budget:.1f}, "
                      f"Mean: {self.moving_avg_growth:.2f}, "
                      f"Std: {self.variance**0.5:.2f}", file=sys.stderr)
                self._spawn(ct)
                self.reinvestment_budget -= 132

    def _spawn(self, ct: Controller):
        pair_idx = (self.spawned // 2) % 4
        sub_idx = self.spawned % 2
        d_idx = self.pairs[pair_idx][sub_idx]
            
        d = DIRECTIONS[d_idx]
        spawn_pos = ct.get_position().add(d)
        
        if ct.can_spawn(spawn_pos):
            ct.spawn_builder(spawn_pos)
            self.spawned += 1
