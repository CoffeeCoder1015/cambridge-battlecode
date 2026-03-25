import sys

from cambc import Controller

from ..Offense.BreakBridges import BreakBridges


class Hound:
    def __init__(self, debug_prints: bool = False):
        self.debug_prints = debug_prints
        self.break_bridges = BreakBridges(debug_prints=debug_prints)

    def _log(self, ct: Controller, message: str) -> None:
        if not self.debug_prints:
            return
        print(
            f"[Hound][R{ct.get_current_round()}][id={ct.get_id()}] {message}",
            file=sys.stderr,
        )

    def compute_enemy_core_target(
        self,
        ct: Controller,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
    ) -> tuple[int, int] | None:
        if core_pos is None or known_symmetry is None:
            return None

        core_x, core_y = core_pos
        max_x = ct.get_map_width() - 1
        max_y = ct.get_map_height() - 1

        if known_symmetry == 101:  # REF_X
            return (max_x - core_x, core_y)
        if known_symmetry == 102:  # REF_Y
            return (core_x, max_y - core_y)
        if known_symmetry == 103:  # ROT
            return (max_x - core_x, max_y - core_y)
        return None

    def try_enter_mode(
        self,
        ct: Controller,
        agentmode: str | None,
        known_symmetry: int | None,
        core_pos: tuple[int, int] | None,
        set_nav_target,
    ) -> tuple[str | None, tuple[int, int] | None]:
        # Enforce one-way transition: only allow None -> HOUND.
        # This guarantees HOUND never overrides GUARDED_CONVEYER.
        if agentmode is not None or known_symmetry is None:
            return agentmode, None

        hound_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)
        if hound_target is None:
            return agentmode, None

        next_mode = "HOUND"
        set_nav_target(*hound_target)

        if self.debug_prints:
            print(
                (
                    f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                    f"entering HOUND mode -> target enemy core at {hound_target} "
                    f"(symmetry={known_symmetry}, core={core_pos})"
                ),
                file=sys.stderr,
            )

        return next_mode, hound_target

    def run(
        self,
        ct: Controller,
        enemy_core_target: tuple[int, int] | None,
        core_pos: tuple[int, int] | None,
        known_symmetry: int | None,
        set_nav_target,
        execute_nav_step,
    ) -> tuple[bool, tuple[int, int] | None]:
        if self.break_bridges.is_enemy_core_visible(ct):
            bridge_target, total_enemy_bridges, occupied_enemy_bridges = (
                self.break_bridges.select_bridge_target_with_stats(ct)
            )
            self._log(
                ct,
                (
                    "enemy core visible; "
                    f"enemy_bridges_seen={total_enemy_bridges} "
                    f"occupied_enemy_bridges={occupied_enemy_bridges}"
                ),
            )
            if bridge_target is not None:
                my_pos = ct.get_position()
                if my_pos.x == bridge_target.x and my_pos.y == bridge_target.y:
                    self._log(
                        ct,
                        (
                            "holding on enemy bridge at "
                            f"({bridge_target.x},{bridge_target.y})"
                        ),
                    )
                    return True, enemy_core_target

                self._log(
                    ct,
                    (
                        f"bridge target selected=({bridge_target.x},{bridge_target.y}) "
                        f"from=({my_pos.x},{my_pos.y})"
                    ),
                )
                set_nav_target(bridge_target.x, bridge_target.y)
                moved = execute_nav_step(ct)
                post_pos = ct.get_position()
                self._log(
                    ct,
                    (
                        f"bridge move result moved={moved} "
                        f"post=({post_pos.x},{post_pos.y}) "
                        f"target=({bridge_target.x},{bridge_target.y})"
                    ),
                )
                # Keep the hound committed to this action even if movement is blocked this turn.
                return True, enemy_core_target
            self._log(ct, "enemy core visible but no open enemy bridge target found")

        if enemy_core_target is None:
            hound_target = self.compute_enemy_core_target(ct, core_pos, known_symmetry)
            if hound_target is None:
                return False, enemy_core_target
            enemy_core_target = hound_target

        set_nav_target(*enemy_core_target)
        return execute_nav_step(ct), enemy_core_target
