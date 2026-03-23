from cambc import Controller, Environment
from .Symmetry.TerrainMemory import SymmetryAnalyzer
from .Symmetry.PropogateSymmetry import SignalPropagator
from .Movement.TangentBug import TangentBug
from .GuardedConveyer.GuardedConveyer import GuardedConveyer
from .GuardedConveyer.GaurdedConveryMove import GaurdedConveryMove
from .Movement.Hound import Hound
from .BridgeBuilding.BfsBuilder import BfsBuilder
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
        self.bfs_builder = BfsBuilder()
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
            self.symmetry_analyzer = SymmetryAnalyzer(ct, core_pos=self.core_pos)
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

        if ct.get_current_round() == 2:
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
        - activated by the presets when bot is built
        '''
        guarded_acted = False
        if self.agentmode == "GUARDED_CONVEYER":
            guarded_acted, _guarded_failed = self.guarded_conveyer.run(ct, nearby_tiles)
            if self.guarded_conveyer.complete:
                # Hand control back to mode selection once guarded conveyor is done.
                self.agentmode = "BRIDGE_BUILDER"
            if (
                not guarded_acted
                and self.guarded_conveyer.should_suppress_main_movement(ct)
            ):
                guarded_acted = True
            if not guarded_acted and self.guarded_conveyer.no_ore_in_scan:
                if self.known_symmetry is not None:
                    guarded_acted = self.bridge_builder.main(ct, self.known_symmetry)
                    if not guarded_acted:
                        guarded_acted = self.gaurded_convery_move.run(ct)
                else:
                    guarded_acted = self.gaurded_convery_move.run(ct)

        '''
        BRIDGE BUILDER MODE
        
        '''
        bridge_builder_acted = False
        if not guarded_acted and self.agentmode == "BRIDGE_BUILDER":
            ore_in_vision = False
            for tile in nearby_tiles:
                try:
                    env = ct.get_tile_env(tile)
                except Exception:
                    continue
                if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                    ore_in_vision = True
                    break

            if ore_in_vision:
                bridge_builder_acted = self.bridge_builder.main(ct, self.known_symmetry)
            else:
                bridge_builder_acted = self.bfs_builder.run(
                    ct=ct,
                    core_pos=self.core_pos,
                    nav=self.nav,
                    set_nav_target=self._set_nav_target,
                )
            if not bridge_builder_acted:
                bridge_builder_acted = self.gaurded_convery_move.run(ct)

        '''
        HOUND MODE
        - enters hound mode if agentmode = None and we know symmetry of the map
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
        MOVEMENT LOGIC (when agent.mode = None)
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

