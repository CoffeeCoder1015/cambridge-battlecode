from cambc import Controller

from .BridgeBuilder.BridgeBuilder import BridgeBuilder
from .Movement.TangentNav import TangentNav
from .Symmetry.TerrainMemory import SymmetryAnalyzer
from .helper import (
    ensure_symmetry_analyzer,
    refresh_core_pos,
)


class BuilderBot:
    def __init__(self) -> None:
        # "DEFAULT" = normal center-target movement, "BRIDGE_BUILDER" = ore/bridge mode.
        self.agentmode = "DEFAULT"
        self.symmetry_analyzer: SymmetryAnalyzer | None = None
        self.bridge_builder = BridgeBuilder()
        self.nav = TangentNav()
        self.core_pos: tuple[int, int] | None = None

    def run(self, ct: Controller) -> None:
        if ct.get_current_round() == 1:
            self.agentmode = "BRIDGE_BUILDER"

        self.core_pos = refresh_core_pos(ct, self.core_pos)

        self.symmetry_analyzer = ensure_symmetry_analyzer(
            ct,
            self.symmetry_analyzer,
            self.core_pos,
        )

        self.symmetry_analyzer.update(ct)
        if self.agentmode == "BRIDGE_BUILDER":
            self.bridge_builder.run(
                ct=ct,
                core_pos=self.core_pos,
                symmetry_analyzer=self.symmetry_analyzer,
            )
            return

        if self.agentmode == "DEFAULT":
            self.nav.attach_terrain_memory(self.symmetry_analyzer.map_history)
            self.nav.run_turn(ct)
            return

        self.nav.attach_terrain_memory(self.symmetry_analyzer.map_history)
        self.nav.run_turn(ct)
