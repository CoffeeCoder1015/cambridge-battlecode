from cambc import Controller, Direction, Environment
from .Symmetry.TerrainMemory import SymmetryAnalyzer
from .Symmetry.PropogateSymmetry import SignalPropagator
from .Movement.TangentBug import TangentBug
from .Movement.ExplorationController import ExplorationController
from .GuardedConveyer.GuardedConveyer import GuardedConveyer
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
        self.hound = Hound(debug_prints=DEBUG_PRINTS)
        self.bridge_builder = BridgeBuilder()
        self._target_set = False
        self.core_pos: tuple[int, int] | None = None
        self.enemy_core_target: tuple[int, int] | None = None
        self._last_nav_target: tuple[int, int] | None = None

        self._reached_center = False
        self._exploration_controller: ExplorationController | None = None
        self._spawn_direction: Direction | None = None

        self.role: str | None = None

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

        if self.role is None:
            self.role = "HOUND" if (ct.get_id() % 4 == 0) else "ECONOMY"
            if self.role == "ECONOMY":
                self.agentmode = "BRIDGE_BUILDER"

        nearby_tiles = ct.get_nearby_tiles()
        """
        SYMMETRY ANALYSIS & PROPAGATION 
        - runs every turn regardless of agentmode
        """

        self.known_symmetry = self.symmetry_analyzer.update(ct)
        self.nav.attach_terrain_memory(self.symmetry_analyzer.map_history)

        if self.role == "HOUND":
            self.agentmode, entered_hound_target = self.hound.try_enter_mode(
                ct=ct,
                agentmode=self.agentmode,
                known_symmetry=self.known_symmetry,
                core_pos=self.core_pos,
                set_nav_target=self._set_nav_target,
            )
            if entered_hound_target is not None:
                self.enemy_core_target = entered_hound_target

        """
        GUARDED CONVEYER MODE
        """
        if self.agentmode == "GUARDED_CONVEYER":
            guarded_acted, _guarded_failed = self.guarded_conveyer.run(ct, nearby_tiles)
            if self.guarded_conveyer.complete:
                self.agentmode = "BRIDGE_BUILDER"

            if guarded_acted or self.guarded_conveyer.should_suppress_main_movement(ct):
                return

            # If guarded mode didn't act, fall back to bridge builder or exploration.
            # We don't return early if ore is visible anymore to avoid idling.
            bridge_acted = self.bridge_builder.main(
                ct=ct,
                known_symmetry=self.known_symmetry,
                core_pos=self.core_pos,
                symmetry_analyzer=self.symmetry_analyzer,
            )
            if bridge_acted:
                return

            if self.role == "ECONOMY":
                if self._do_exploration(ct):
                    return
                return

        """
        BRIDGE BUILDER MODE
        """
        if self.agentmode == "BRIDGE_BUILDER":
            bridge_builder_acted = self.bridge_builder.main(
                ct=ct,
                known_symmetry=self.known_symmetry,
                core_pos=self.core_pos,
                symmetry_analyzer=self.symmetry_analyzer,
            )
            if bridge_builder_acted:
                return

            # Even if ore is visible, if the bridge builder didn't act (e.g. unreachable), explore!
            if self.role == "ECONOMY":
                if self._do_exploration(ct):
                    return
                return

        """
        HOUND MODE
        """
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

        """
        FALLBACK MOVEMENT LOGIC
        - ECONOMY: direct to exploration (skip center)
        - HOUND: Phase 1 (center) -> Phase 2 (exploration)
        """
        my_pos = ct.get_position()

        if self.role == "ECONOMY":
            if self._has_visible_ore(ct):
                self._exploration_controller = None
                return
            if self._do_exploration(ct):
                return
            return

        if not self._target_set:
            self._set_nav_target(ct.get_map_width() // 2, ct.get_map_height() // 2)

        center_acted = self._execute_nav_step(ct)

        at_center = (
            self._last_nav_target is not None
            and my_pos.x == self._last_nav_target[0]
            and my_pos.y == self._last_nav_target[1]
        )

        if at_center or not center_acted:
            if self._do_exploration(ct):
                return

            return

    def _set_nav_target(self, tx: int, ty: int) -> None:
        self._last_nav_target, self._target_set = set_nav_target(
            nav=self.nav,
            last_nav_target=self._last_nav_target,
            tx=tx,
            ty=ty,
        )

    def _execute_nav_step(self, ct: Controller) -> bool:
        return execute_nav_step(ct, self.nav)

    def _get_spawn_direction(self, ct: Controller) -> Direction:
        if self._spawn_direction is None and self.core_pos is not None:
            my_pos = ct.get_position()
            dx = my_pos.x - self.core_pos[0]
            dy = my_pos.y - self.core_pos[1]
            dx = max(-1, min(1, dx))
            dy = max(-1, min(1, dy))
            for d, vec in self._DIR_VECTORS.items():
                if vec == (dx, dy):
                    self._spawn_direction = d
                    break
        return self._spawn_direction or Direction.NORTH

    _DIR_VECTORS: dict[Direction, tuple[int, int]] = {
        Direction.NORTH: (0, -1),
        Direction.NORTHEAST: (1, -1),
        Direction.EAST: (1, 0),
        Direction.SOUTHEAST: (1, 1),
        Direction.SOUTH: (0, 1),
        Direction.SOUTHWEST: (-1, 1),
        Direction.WEST: (-1, 0),
        Direction.NORTHWEST: (-1, -1),
    }

    def _do_exploration(self, ct: Controller) -> bool:
        if self._exploration_controller is None:
            spawn_dir = self._get_spawn_direction(ct)
            self._exploration_controller = ExplorationController(
                spawn_direction=spawn_dir,
                map_width=ct.get_map_width(),
                map_height=ct.get_map_height(),
            )

        return self._exploration_controller.step(ct)

    def _has_visible_ore(self, ct: Controller) -> bool:
        for tile in ct.get_nearby_tiles():
            try:
                if ct.get_tile_env(tile) == Environment.ORE_TITANIUM:
                    return True
            except Exception:
                continue
        return False
