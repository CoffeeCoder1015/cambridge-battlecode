import sys

from collections import deque
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
        
        # Adaptive Growth (25-round Sliding Window)
        self.growth_history = deque(maxlen=25)
        self.sum_x = 0
        self.sum_x2 = 0
        self.moving_avg_growth = 0
        self.variance = 0
        
        # Opposite direction index pairs for symmetry: (N,S), (E,W), (NE,SW), (SE,NW)
        self.pairs = [(0, 4), (2, 6), (1, 5), (3, 7)]
        
        # Adaptive Expense Tracking
        self.reserve_buffer = 120  # Start with enough to build one full Harvester pipeline
        
        # Resource Drain Wave (Aggressive Spawning Mode)
        self.drain_wave_active = False
        self.drain_wave_rounds_left = 0
        self.DRAIN_WAVE_DURATION = 20  # Spawn every round for 20 rounds

    def run(self, ct: Controller):
        res = ct.get_global_resources()
        titanium = res[0]
        rnd = ct.get_current_round()
        
        # 0.1 Adaptive Expense Tracking
        # If the swarm bottomed out the bank entirely (< 3 Ti for a conveyor),
        # they wanted to spend more but starved. Ratchet up the hold buffer incrementally!
        if rnd > 1 and titanium < 3:
            self.reserve_buffer += 50
            print(f"[Core] Swarm Starved! Ratcheting reserve buffer to {self.reserve_buffer} Ti", file=sys.stderr)
        elif rnd > 1 and titanium > self.reserve_buffer + 100:
            # Slow decay to find the lowest safe floor
            self.reserve_buffer = max(120, self.reserve_buffer - 1)

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
        
        # 0.6 Dynamic reserve floor — always tethered to live harvester cost
        harv_c_early = ct.get_harvester_cost()[0]
        conv_c_early = ct.get_conveyor_cost()[0]
        min_reserve = harv_c_early + 3 * conv_c_early
        self.reserve_buffer = max(self.reserve_buffer, min_reserve)

        self.last_titanium = titanium

        if ct.get_action_cooldown() == 0:
            # DRAIN WAVE: Aggressive spawning — one bot every round
            # Floor tied to dynamic reserve so we can still build harvesters
            if self.drain_wave_active:
                bot_c_dw = ct.get_builder_bot_cost()[0]
                if self.drain_wave_rounds_left > 0 and titanium >= self.reserve_buffer + bot_c_dw:
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

            # 2. Flow Reinvestment (Profit + Dynamic Margin Staircasing)
            # Tether cost to live game stats:
            bot_c = ct.get_builder_bot_cost()[0]
            harv_c = ct.get_harvester_cost()[0]
            conv_c = ct.get_conveyor_cost()[0]
            current_deployment_cost = bot_c + harv_c + conv_c
            
            # Dynamic margin based on scale percent AND current wealth:
            # Scale Penalty: -5% margin per +1.0 scale percent above 100.0%.
            # Wealth Bonus: -10% margin per 500 Titanium in the bank.
            # Clamps at -150% (-1.50) to maintain aggressive spending.
            current_scale = getattr(ct, 'get_scale_percent', lambda: 100.0)()
            scale_penalty = (current_scale - 100.0) * 0.05
            wealth_bonus = (titanium / 500) * 0.10
            
            margin_pct = 0.10 - scale_penalty - wealth_bonus
            margin_pct = max(-1.50, min(0.20, margin_pct))
            
            target_budget = current_deployment_cost * (1.0 + margin_pct)
            
            # 2.5 Wealthy Overdrive
            # If we are overflowing with cash (3x the discovered expense buffer), 
            # we just dump it into bots regardless of the profit debt ledger.
            wealth_overdrive = titanium > self.reserve_buffer * 3
            
            # Require titanium to be >= the discovered reserve buffer (plus the bot cost we are about to spend).
            # This ensures we NEVER accidentally drain the bank and starve bots from purchasing harvesters!
            if (self.reinvestment_budget >= target_budget or wealth_overdrive) and titanium >= self.reserve_buffer + bot_c:
                print(f"[Core] Flow Spawn{' (OVERDRIVE)' if wealth_overdrive else ''}. "
                      f"Budget: {self.reinvestment_budget:.1f}/{target_budget:.1f}, "
                      f"Margin: {margin_pct*100:.1f}%, Scale: {current_scale:.1f}%", file=sys.stderr)
                self._spawn(ct)
                # We ALWAYS deduct the full deployment cost from our internal profit tracking.
                # If target_budget is negative, we go heavily into debt, ensuring the
                # "zig-zag" burst spending eventually stops to let profit catch back up!
                self.reinvestment_budget -= current_deployment_cost

    def _spawn(self, ct: Controller):
        pair_idx = (self.spawned // 2) % 4
        sub_idx = self.spawned % 2
        preferred_d_idx = self.pairs[pair_idx][sub_idx]
            
        # Try preferred direction first, then scan all 8 to avoid getting entombed
        for offset in range(8):
            d_idx = (preferred_d_idx + offset) % 8
            d = DIRECTIONS[d_idx]
            spawn_pos = ct.get_position().add(d)
            
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.spawned += 1
                return
