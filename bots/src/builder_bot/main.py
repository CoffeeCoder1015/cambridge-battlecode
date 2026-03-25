from cambc import Controller
from .Symmetry.TerrainMemory import SymmetryAnalyzer
from .Symmetry.PropogateSymmetry import SignalPropagator
from .Movement.TangentBug import TangentBug
from .GuardedConveyer.GuardedConveyer import GuardedConveyer
from .GuardedConveyer.GaurdedConveryMove import GaurdedConveryMove
from .Movement.Hound import Hound
from .BridgeBuilding.BridgeBuilder import BridgeBuilder
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
        self.bridge_builder = BridgeBuilder()
        self._target_set = False
        self.core_pos: tuple[int, int] | None = None
        self.enemy_core_target: tuple[int, int] | None = None
        self._last_nav_target: tuple[int, int] | None = None

        self.agentmode = None 
        # None = mode selection, "GUARDED_CONVEYER" = guarded conveyor mode, "BRIDGE_BUILDER" = bridge builder mode, "HOUND" = hound mode

        self.agentrole = "Default" 
        # "Default" = default role, "Builder" = builder role, 

    def run(self, ct: Controller) -> None:

        self.core_pos = refresh_core_pos(ct, self.core_pos)
        
        if self.symmetry_analyzer is None:
            self.symmetry_analyzer = SymmetryAnalyzer(
                ct,
                core_pos=self.core_pos,
                debug_prints=DEBUG_PRINTS,
            )
        elif self.core_pos is not None:
            self.symmetry_analyzer.update_core_pos(self.core_pos)

        if self.signal_propagator is None:
            self.signal_propagator = SignalPropagator(core_pos=ct.get_position())

        """
        Presets for modes:
        """
        if ct.get_current_round() == 1:
            self.agentmode = "BRIDGE_BUILDER"
            self.agentrole = "Builder"

        if ct.get_current_round() == 400:
            self.agentmode = "BRIDGE_BUILDER"
            self.agentrole = "Builder"


        nearby_tiles = ct.get_nearby_tiles()
        '''
        SYMMETRY ANALYSIS & PROPAGATION 
        - runs every turn regardless of agentmode
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
        if self.agentmode == "GUARDED_CONVEYER":
            guarded_acted, _guarded_failed = self.guarded_conveyer.run(ct, nearby_tiles)
            if self.guarded_conveyer.complete:
                self.agentmode = "BRIDGE_BUILDER"
            
            if guarded_acted or self.guarded_conveyer.should_suppress_main_movement(ct):
                return # Yield turn. Do not fall through to other modes or movement.

            if self.guarded_conveyer.no_ore_in_scan:
                bridge_acted = self.bridge_builder.main(
                    ct=ct,
                    known_symmetry=self.known_symmetry,
                    core_pos=self.core_pos,
                    symmetry_analyzer=self.symmetry_analyzer,
                )
                if bridge_acted:
                    return
                
                # If bridge didn't act, try conveyer move
                self.gaurded_convery_move.run(ct)
                return # Yield turn.

        '''
        BRIDGE BUILDER MODE
        '''
        if self.agentmode == "BRIDGE_BUILDER":
            bridge_builder_acted = self.bridge_builder.main(
                ct=ct,
                known_symmetry=self.known_symmetry,
                core_pos=self.core_pos,
                symmetry_analyzer=self.symmetry_analyzer,
            )
            # If the bridge builder handled the turn (including waiting), exit immediately.
            if bridge_builder_acted:
                return 
            
            # If it explicitly returned False, try the fallback conveyer move.
            conveyer_moved = self.gaurded_convery_move.run(ct)
            if conveyer_moved:
                return

        '''
        HOUND MODE
        '''
        if self.agentmode == "HOUND":
            hound_acted, self.enemy_core_target = self.hound.run(
                ct=ct,
                enemy_core_target=self.enemy_core_target,
                core_pos=self.core_pos,
                known_symmetry=self.known_symmetry,
                set_nav_target=self._set_nav_target,
                execute_nav_step=self._execute_nav_step,
            )
            if hound_acted:
                return

        '''
        FALLBACK MOVEMENT LOGIC
        - Only reached if NO mode handled the turn.
        '''
        # We don't need all those boolean flags anymore because we would have returned early!
        if not self._target_set:
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

