from cambc import Controller, Direction, EntityType, Environment
from .TerrainMemory import SymmetryAnalyzer
from .PropogateSymmetry import SignalPropagator
from .TangentBug import TangentBug
from .GuardedConveyer import GuardedConveyer
from .GaurdedConveryMove import GaurdedConveryMove

import sys
import random


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


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

    def run(self, ct: Controller) -> None:

        if self.symmetry_analyzer is None:
            self.symmetry_analyzer = SymmetryAnalyzer(ct)

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


        '''
        GUARDED CONVEYER MODE
        '''
        guarded_acted = False
        if self.agentmode == "GUARDED_CONVEYER":
            guarded_acted, guarded_failed = self.guarded_conveyer.run(ct, nearby_tiles)
            if not guarded_acted and self.guarded_conveyer.no_ore_in_scan:
                guarded_acted = self.gaurded_convery_move.run(ct)
                if ct.get_current_round() < 100:
                    print(
                        (
                            f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                            f"no ore in scan -> random cardinal move acted={guarded_acted}"
                        ),
                        file=sys.stderr,
                    )
            if ct.get_current_round() < 100:
                print(
                    (
                        f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                        f"guarded_mode acted={guarded_acted} failed={guarded_failed}"
                    ),
                    file=sys.stderr,
                )
            if guarded_failed:
                if ct.get_current_round() < 100:
                    print(
                        (
                            f"[BuilderBot id={ct.get_id()} r={ct.get_current_round()}] "
                            "guarded mode reported hard failure; will keep retrying"
                        ),
                        file=sys.stderr,
                    )




        '''
        MOVEMENT LOGIC
        '''

        if not guarded_acted:
            # Set a navigation target on first run (map centre as default exploration goal)
            if not self._target_set:
                self.nav.set_target(ct.get_map_width() // 2, ct.get_map_height() // 2)
                self._target_set = True
            move_dir = self.nav.next_move(ct)

            if move_dir is not None:
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

                if ct.can_move(move_dir):
                    ct.move(move_dir)

