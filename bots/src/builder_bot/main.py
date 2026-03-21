from cambc import Controller, Direction, EntityType, Environment
from .TerrainMemory import SymmetryAnalyzer
from .PropogateSymmetry import SignalPropagator
from .TangentBug import TangentBug

import sys
import random


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class BuilderBot:
    def __init__(self):
        self.symmetry_analyzer: SymmetryAnalyzer | None = None
        self.signal_propagator: SignalPropagator | None = None
        self.known_symmetry = None
        self.nav = TangentBug()
        self._target_set = False

    def run(self, ct: Controller) -> None:

        if self.symmetry_analyzer is None:
            self.symmetry_analyzer = SymmetryAnalyzer(ct)

        if self.signal_propagator is None:
            self.signal_propagator = SignalPropagator(core_pos=ct.get_position())

        '''
        SYMMETRY ANALYSIS & PROPAGATION 
        '''

        # Try to find symmetry based on surroundings
        self.known_symmetry = self.symmetry_analyzer.update(ct)
        # Read markers and propagate signal back to core
        self.signal_propagator.process_and_propagate(ct, self.known_symmetry)

        '''
        MOVEMENT LOGIC
        '''

        # Set a navigation target on first run (map centre as default exploration goal)
        if not self._target_set:
            self.nav.set_target(ct.get_map_width() // 2, ct.get_map_height() // 2)
            self._target_set = True

        move_dir = self.nav.next_move(ct)
        if move_dir is not None:
            move_pos = ct.get_position().add(move_dir)

            # Road placement: build a road on the target tile if it is not yet
            # passable (i.e. it is an empty or ore tile) and there is no friendly
            # marker sitting on it that we want to preserve.
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

        # --- Harvest ore on any adjacent tile ---
        for d in Direction:
            check_pos = ct.get_position().add(d)
            if ct.can_build_harvester(check_pos):
                ct.build_harvester(check_pos)
                break
