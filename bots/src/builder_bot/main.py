from cambc import Controller
from .Symmetry.TerrainMemory import SymmetryAnalyzer
from .Symmetry.PropogateSymmetry import SignalPropagator
from .Movement.TangentBug import TangentBug
from .GuardedConveyer.GuardedConveyer import GuardedConveyer
from .GuardedConveyer.GaurdedConveryMove import GaurdedConveryMove
from .Movement.Hound import Hound
from .helpers import execute_nav_step, refresh_core_pos, set_nav_target

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

        self.core_pos = refresh_core_pos(ct, self.core_pos)

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
            guarded_acted, _guarded_failed = self.guarded_conveyer.run(ct, nearby_tiles)
            if (
                not guarded_acted
                and self.guarded_conveyer.should_suppress_main_movement(ct)
            ):
                guarded_acted = True
            if not guarded_acted and self.guarded_conveyer.no_ore_in_scan:
                guarded_acted = self.gaurded_convery_move.run(ct)

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

    def _set_nav_target(self, tx: int, ty: int) -> None:
        self._last_nav_target, self._target_set = set_nav_target(
            nav=self.nav,
            last_nav_target=self._last_nav_target,
            tx=tx,
            ty=ty,
        )

    def _execute_nav_step(self, ct: Controller) -> bool:
        return execute_nav_step(ct, self.nav)

