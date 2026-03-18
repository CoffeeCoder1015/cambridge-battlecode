from cambc import Controller, Direction

DIRECTIONS = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST
]

class Core:
    def __init__(self):
        self.spawned = 0
        self.required_titanium = 0 # Staircase floor
        self.pack_remaining = 0
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
        self.last_titanium = titanium

        if ct.get_action_cooldown() == 0:
            # 1. Opening Sequence (Max 4 bots initially)
            if rnd < 60:
                if self.spawned < 4 and titanium >= 20:
                    self._spawn(ct)
                    if self.spawned == 4:
                        # Set first staircase floor (Recoup ~400 Ti from opening + 10% profit)
                        self.required_titanium = titanium + 440
                return

            # 2. Staircase Logic: Only spawn if we hit the profit target
            if self.pack_remaining > 0:
                # Continue current pack
                if titanium >= 20:
                    self._spawn(ct)
            elif titanium >= max(600, self.required_titanium):
                # Calculate dynamic pack size: 0.5 * growth rate (min 2)
                # We use a multiplier to convert growth/round into a reasonable batch
                # If growth is 10/rd, pack is ~5.
                pack_size = max(2, int(self.moving_avg_growth * 0.5))
                if pack_size % 2 != 0:
                    pack_size += 1 # Maintain pair symmetry
                
                self.pack_remaining = pack_size
                # Next floor = Pre-pack Bank + (bots * cost * 1.1)
                self.required_titanium = titanium + (pack_size * 132)
                
                self._spawn(ct)

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
            if self.pack_remaining > 0:
                self.pack_remaining -= 1
