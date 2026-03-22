from cambc import Controller, Direction, EntityType, Environment
from .TerrainMemory import SymmetryAnalyzer
from .PropogateSymmetry import SignalPropagator
from .TangentBug import TangentBug
from .GuardedConveyer import GuardedConveyer
from .GaurdedConveryMove import GaurdedConveryMove

import sys
import random


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
DEBUG_PRINTS = False


class BuilderBot:
    def __init__(self):
        self.symmetry_analyzer: SymmetryAnalyzer | None = None
        self.signal_propagator: SignalPropagator | None = None
        self.known_symmetry = None
        self.nav = TangentBug()
        self.guarded_conveyer = GuardedConveyer()
        self.gaurded_convery_move = GaurdedConveryMove()
        self._target_set = False
        self.agentmode = None
        self.core_pos: tuple[int, int] | None = None
        self.enemy_core_target: tuple[int, int] | None = None
        self._last_nav_target: tuple[int, int] | None = None

    def run(self, ct: Controller) -> None:

        self._refresh_core_pos(ct)

        if self.symmetry_analyzer is None:
            self.symmetry_analyzer = SymmetryAnalyzer(ct, core_pos=self.core_pos)
        elif self.core_pos is not None:
            self.symmetry_analyzer.update_core_pos(self.core_pos)

        if self.signal_propagator is None:
            self.signal_propagator = SignalPropagator(core_pos=ct.get_position())

        """
        Presets for modes:
        """
        if ct.get_current_round() == 1:
            self.agentmode = "GUARDED_CONVEYER"

        nearby_tiles = ct.get_nearby_tiles()
        '''
        SYMMETRY ANALYSIS & PROPAGATION 
        '''

        # Try to find symmetry based on surroundings
        self.known_symmetry = self.symmetry_analyzer.update(ct)
        # Read markers and propagate signal back to core
        #self.signal_propagator.process_and_propagate(ct, self.known_symmetry)

        self._try_enter_hound_mode(ct)


        '''
        GUARDED CONVEYER MODE
        '''
        guarded_acted = False
        if self.agentmode == "GUARDED_CONVEYER":
            guarded_acted, guarded_failed = self.guarded_conveyer.run(ct, nearby_tiles)
            if (
                not guarded_acted
                and self.guarded_conveyer.should_suppress_main_movement(ct)
            ):
                guarded_acted = True
                if DEBUG_PRINTS and ct.get_current_round() < 100:
                    print(
                        (
                            f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                            "suppressing fallback movement during ore finalize sequence"
                        ),
                        file=sys.stderr,
                    )
            if not guarded_acted and self.guarded_conveyer.no_ore_in_scan:
                guarded_acted = self.gaurded_convery_move.run(ct)
                if DEBUG_PRINTS and ct.get_current_round() < 100:
                    print(
                        (
                            f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                            f"no ore in scan -> random cardinal move acted={guarded_acted}"
                        ),
                        file=sys.stderr,
                    )
            if DEBUG_PRINTS and ct.get_current_round() < 100:
                print(
                    (
                        f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                        f"guarded_mode acted={guarded_acted} failed={guarded_failed}"
                    ),
                    file=sys.stderr,
                )
            if guarded_failed:
                if DEBUG_PRINTS and ct.get_current_round() < 100:
                    print(
                        (
                            f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                            "guarded mode reported hard failure; will keep retrying"
                        ),
                        file=sys.stderr,
                    )




        '''
        HOUND MODE
        '''
        hound_acted = False
        if not guarded_acted and self.agentmode == "HOUND":
            hound_acted = self._run_hound_mode(ct)

        '''
        MOVEMENT LOGIC
        '''
        if not guarded_acted and self.agentmode != "HOUND" and not hound_acted:
            if not self._target_set:
                # Set a navigation target on first run (map centre as default exploration goal)
                self._set_nav_target(ct.get_map_width() // 2, ct.get_map_height() // 2)
            self._execute_nav_step(ct)

    def _refresh_core_pos(self, ct: Controller) -> None:
        for b_id in ct.get_nearby_buildings():
            try:
                if (
                    ct.get_entity_type(b_id) == EntityType.CORE
                    and ct.get_team(b_id) == ct.get_team()
                ):
                    pos = ct.get_position(b_id)
                    self.core_pos = (pos.x, pos.y)
                    return
            except Exception:
                continue

    def _compute_enemy_core_target(self, ct: Controller) -> tuple[int, int] | None:
        if self.core_pos is None or self.known_symmetry is None:
            return None

        core_x, core_y = self.core_pos
        max_x = ct.get_map_width() - 1
        max_y = ct.get_map_height() - 1

        if self.known_symmetry == 101:  # REF_X
            return (max_x - core_x, core_y)
        if self.known_symmetry == 102:  # REF_Y
            return (core_x, max_y - core_y)
        if self.known_symmetry == 103:  # ROT
            return (max_x - core_x, max_y - core_y)
        return None

    def _set_nav_target(self, tx: int, ty: int) -> None:
        next_target = (tx, ty)
        if self._last_nav_target != next_target:
            self.nav.set_target(tx, ty)
            self._last_nav_target = next_target
        self._target_set = True

    def _try_enter_hound_mode(self, ct: Controller) -> None:
        # Enforce one-way transition: only allow None -> HOUND.
        # This guarantees HOUND never overrides GUARDED_CONVEYER.
        if self.agentmode is not None or self.known_symmetry is None:
            return

        hound_target = self._compute_enemy_core_target(ct)
        if hound_target is None:
            return

        self.agentmode = "HOUND"
        self.enemy_core_target = hound_target
        self._set_nav_target(*hound_target)
        if DEBUG_PRINTS:
            print(
                (
                    f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                    f"entering HOUND mode -> target enemy core at {hound_target} "
                    f"(symmetry={self.known_symmetry}, core={self.core_pos})"
                ),
                file=sys.stderr,
            )

    def _run_hound_mode(self, ct: Controller) -> bool:
        if self.enemy_core_target is None:
            hound_target = self._compute_enemy_core_target(ct)
            if hound_target is None:
                return False
            self.enemy_core_target = hound_target

        self._set_nav_target(*self.enemy_core_target)
        return self._execute_nav_step(ct)

    def _execute_nav_step(self, ct: Controller) -> bool:
        move_dir = self.nav.next_move(ct)
        if move_dir is None:
            return False

        acted = False
        move_pos = ct.get_position().add(move_dir)
        if not ct.is_tile_passable(move_pos):
            has_friendly_marker = any(
                ct.get_entity_type(eid) == EntityType.MARKER
                and ct.get_team(eid) == ct.get_team()
                and ct.get_position(eid) == move_pos
                for eid in ct.get_nearby_entities()
            )
            if ct.can_build_road(move_pos) and not has_friendly_marker:
                ct.build_road(move_pos)
                acted = True

        if ct.can_move(move_dir):
            ct.move(move_dir)
            acted = True

        return acted

