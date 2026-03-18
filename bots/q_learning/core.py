from cambc import Controller, Direction

DIRECTIONS = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST
]

class Core:
    def __init__(self):
        self.spawn_index = 0
        self.spawned = 0
        self.required_titanium = 0 # Staircase floor
        self.pack_remaining = 0

    def run(self, ct: Controller):
        if ct.get_action_cooldown() == 0:
            res = ct.get_global_resources()
            titanium = res[0]
            rnd = ct.get_current_round()
            
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
                # Start new pack of 8
                self.pack_remaining = 8
                # Next floor = Pre-pack Bank + 1056 (8 bots * (20 spawn + 100 infra) * 1.1)
                self.required_titanium = titanium + 1056
                self._spawn(ct)

    def _spawn(self, ct: Controller):
        d = DIRECTIONS[self.spawn_index % 8]
        self.spawn_index += 1
        spawn_pos = ct.get_position().add(d)
        if ct.can_spawn(spawn_pos):
            ct.spawn_builder(spawn_pos)
            self.spawned += 1
            if self.pack_remaining > 0:
                self.pack_remaining -= 1
