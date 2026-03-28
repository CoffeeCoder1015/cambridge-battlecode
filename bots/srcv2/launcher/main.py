import random
from cambc import Controller, EntityType, Position

class Launcher:
    def __init__(self) -> None:
        self._rng = random.Random()
        self._debug_enabled = True
        self._max_attempt_logs = 8

    def _dbg(self, ct: Controller, msg: str) -> None:
        if not self._debug_enabled:
            return
        pos = ct.get_position()
        print(
            f"[R{ct.get_current_round()}][ID={ct.get_id()}][Launcher]"
            f"[{pos.x},{pos.y}] {msg}"
        )

    def run(self, ct: Controller) -> None:
        # Actions require cooldown == 0
        if ct.get_action_cooldown() > 0:
            return

        my_id = ct.get_id()
        my_team = ct.get_team()
        
        # FIX: Restrict the unit scan to a squared distance of 2 (adjacent tiles)
        nearby_all_units = ct.get_nearby_units(2) 
        
        candidate_builders: list[int] = []
        for unit_id in nearby_all_units:
            if unit_id == my_id:
                continue
                
            # Must be a BUILDER_BOT
            if ct.get_entity_type(unit_id) != EntityType.BUILDER_BOT:
                continue
                
            # Only pick up enemy bots
            if ct.get_team(unit_id) == my_team:
                continue
                
            candidate_builders.append(unit_id)

        # get_nearby_tiles defaults to vision radius, which is fine for targets
        targets = ct.get_nearby_tiles()
        
        if not candidate_builders or not targets:
            return

        self._rng.shuffle(candidate_builders)
        self._rng.shuffle(targets)

        for unit_id in candidate_builders:
            # API expects `bot_pos` as a Position, not the unit_id
            bot_pos = ct.get_position(unit_id)
            attempts = 0

            for target in targets:
                # can_launch takes (bot_pos: Position, target: Position)
                if ct.can_launch(bot_pos, target):
                    ct.launch(bot_pos, target)
                    self._dbg(
                        ct, 
                        f"🚀 LAUNCH SUCCESS: bot={unit_id} "
                        f"from=({bot_pos.x},{bot_pos.y}) to=({target.x},{target.y})"
                    )
                    return # Exit after one successful launch to respect cooldown rules
                    
                attempts += 1

            if attempts > self._max_attempt_logs:
                self._dbg(
                    ct,
                    f"Bot id={unit_id} at ({bot_pos.x},{bot_pos.y}) had no valid launch target. "
                    f"Suppressed {attempts - self._max_attempt_logs} logs."
                )

        self._dbg(ct, "No valid launch targets found this turn.")