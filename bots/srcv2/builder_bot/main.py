from cambc import Controller

from .Movement.TangentNav import TangentNav
from .Symmetry.TerrainMemory import SymmetryAnalyzer
from .helper import (
    ensure_symmetry_analyzer,
    refresh_core_pos,
)


class BuilderBot:
    def __init__(self) -> None:
        self.symmetry_analyzer: SymmetryAnalyzer | None = None
        self.core_pos: tuple[int, int] | None = None
        self.nav = TangentNav()

    def run(self, ct: Controller) -> None:
        self.core_pos = refresh_core_pos(ct, self.core_pos)

        self.symmetry_analyzer = ensure_symmetry_analyzer(
            ct,
            self.symmetry_analyzer,
            self.core_pos,
        )

        self.symmetry_analyzer.update(ct)
        self.nav.attach_terrain_memory(self.symmetry_analyzer.map_history)
        self.nav.run_turn(ct)
