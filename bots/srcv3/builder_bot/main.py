import sys

from cambc import Controller, EntityType

from .Movement.TangentNav import TangentNav
from .Symmetry.TerrainMemory import SymmetryAnalyzer

# Set to True only when actively debugging; False for tournament runs.
_DEBUG = True
_DEBUG_MAX_ROUND = 150


class BuilderBot:
    def __init__(self) -> None:
        self.symmetry_analyzer: SymmetryAnalyzer | None = None
        self.core_pos: tuple[int, int] | None = None
        self.nav = TangentNav()
        self._last_target: tuple[int, int] | None = None

    def run(self, ct: Controller) -> None:
        self.core_pos = self._refresh_core_pos(ct, self.core_pos)
        cur = ct.get_position()

        if self.symmetry_analyzer is None:
            self.symmetry_analyzer = SymmetryAnalyzer(
                ct,
                core_pos=self.core_pos,
            )
        elif self.core_pos is not None:
            self.symmetry_analyzer.update_core_pos(self.core_pos)

        self.symmetry_analyzer.update(ct)
        self.nav.attach_terrain_memory(self.symmetry_analyzer.map_history)

        target = (ct.get_map_width() // 2, ct.get_map_height() // 2)
        if self._last_target != target:
            self.nav.set_target(target[0], target[1], cur.x, cur.y)
            self._last_target = target
            self._dbg(ct, f"New target -> {target}")

        move_dir = self.nav.next_move(ct)
        if move_dir is None:
            self._dbg(ct, "No move selected.")
            return

        move_pos = cur.add(move_dir)
        self._dbg(ct, f"Move {move_dir.name} -> ({move_pos.x},{move_pos.y})")

        if ct.get_action_cooldown() == 0 and ct.can_build_road(move_pos):
            ct.build_road(move_pos)

        if ct.get_move_cooldown() == 0 and ct.can_move(move_dir):
            ct.move(move_dir)
        else:
            self._dbg(
                ct,
                f"Blocked (move_cd={ct.get_move_cooldown()}, "
                f"can_move={ct.can_move(move_dir)})",
            )

    @staticmethod
    def _refresh_core_pos(
        ct: Controller,
        current: tuple[int, int] | None,
    ) -> tuple[int, int] | None:
        for b_id in ct.get_nearby_buildings():
            try:
                if (
                    ct.get_entity_type(b_id) == EntityType.CORE
                    and ct.get_team(b_id) == ct.get_team()
                ):
                    pos = ct.get_position(b_id)
                    return (pos.x, pos.y)
            except Exception:
                continue
        return current

    @staticmethod
    def _dbg(ct: Controller, msg: str) -> None:
        if _DEBUG and ct.get_current_round() < _DEBUG_MAX_ROUND:
            pos = ct.get_position()
            print(
                f"[R{ct.get_current_round()}][BB][{pos.x},{pos.y}] {msg}",
                file=sys.stderr,
            )
