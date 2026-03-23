from cambc import Controller, Direction, EntityType, Environment
from .Symmetry.TerrainMemory import SymmetryAnalyzer
from .Symmetry.PropogateSymmetry import SignalPropagator
from .Movement.TangentBug import TangentBug
from .GuardedConveyer.GuardedConveyer import GuardedConveyer
from .GuardedConveyer.GaurdedConveryMove import GaurdedConveryMove
from .Movement.Hound import Hound

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
        self.hound = Hound(debug_prints=DEBUG_PRINTS)
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

        self.agentmode, entered_hound_target = self.hound.try_enter_mode(
            ct=ct,
            agentmode=self.agentmode,
            known_symmetry=self.known_symmetry,
            core_pos=self.core_pos,
            set_nav_target=self._set_nav_target,
        )
        if entered_hound_target is not None:
            self.enemy_core_target = entered_hound_target


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
            hound_acted, self.enemy_core_target = self.hound.run(
                ct=ct,
                enemy_core_target=self.enemy_core_target,
                core_pos=self.core_pos,
                known_symmetry=self.known_symmetry,
                set_nav_target=self._set_nav_target,
                execute_nav_step=self._execute_nav_step,
            )

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

    def _set_nav_target(self, tx: int, ty: int) -> None:
        next_target = (tx, ty)
        if self._last_nav_target != next_target:
            self.nav.set_target(tx, ty)
            self._last_nav_target = next_target
        self._target_set = True

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

