from cambc import Controller, Direction, EntityType
from .TerrainMemory import SymmetryAnalyzer
from .PropogateSymmetry import SignalPropagator

import sys
import random


DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class BuilderBot:
    def __init__(self):
        self.symmetry_analyzer: SymmetryAnalyzer | None = None
        self.signal_propagator: SignalPropagator | None = None
        self.known_symmetry = None

    def run(self, ct: Controller) -> None:
        
        '''
        SYMMETRY ANALYSIS & PROPAGATION 
        '''
        if self.symmetry_analyzer is None:
            self.symmetry_analyzer = SymmetryAnalyzer(ct)

        if self.signal_propagator is None:
            self.signal_propagator = SignalPropagator(core_pos=ct.get_position())

        self.known_symmetry = self.symmetry_analyzer.update(ct)
        self.signal_propagator.process_and_propagate(ct, self.known_symmetry)

        '''
        MOVEMENT LOGIC
        '''
        move_dir = random.choice(DIRECTIONS)
        if move_dir is not None:
            move_pos = ct.get_position().add(move_dir)

            # Build road on the target tile if safe (no friendly marker there)
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
