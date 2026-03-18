from cambc import Controller, Direction

DIRECTIONS = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST
]

class Core:
    def __init__(self):
        self.spawned = 0
        self.reinvestment_budget = 0 # Available titanium for spawning
        self.last_titanium = 0
        self.moving_avg_growth = 0 # EMA of titanium income
        # Opposite direction index pairs for symmetry: (N,S), (E,W), (NE,SW), (SE,NW)
        self.pairs = [(0, 4), (2, 6), (1, 5), (3, 7)]

    def run(self, ct: Controller):
        res = ct.get_global_resources()
        titanium = res[0]
        rnd = ct.get_current_round()

        # 0. Growth tracking (Income EMA)
        if rnd > 0:
            delta = max(0, titanium - self.last_titanium)
            self.moving_avg_growth = self.moving_avg_growth * 0.95 + delta * 0.05
            
            # 0.5. Budget Accrual (Flow Economy)
            # Reinvest 80% of growth if above safety threshold
            if self.moving_avg_growth >= 1.2:
                self.reinvestment_budget += self.moving_avg_growth * 0.8
        
        self.last_titanium = titanium

        if ct.get_action_cooldown() == 0:
            # 1. Opening Sequence (Max 4 bots initially) - "Free" or low-cost start
            if rnd < 60:
                if self.spawned < 4 and titanium >= 20:
                    self._spawn(ct)
                return

            # 2. Flow Reinvestment: Spawn if budget allows (Cost per bot ~132)
            if self.reinvestment_budget >= 132 and titanium >= 20:
                self._spawn(ct)
                self.reinvestment_budget -= 132

    def _spawn(self, ct: Controller):
        # Opposite direction index pairs for symmetry: (N,S), (E,W), (NE,SW), (SE,NW)
        # Select pair based on total spawned bots / 2
        pair_idx = (self.spawned // 2) % 4
        sub_idx = self.spawned % 2
        d_idx = self.pairs[pair_idx][sub_idx]
            
        d = DIRECTIONS[d_idx]
        spawn_pos = ct.get_position().add(d)
        
        if ct.can_spawn(spawn_pos):
            ct.spawn_builder(spawn_pos)
            self.spawned += 1
