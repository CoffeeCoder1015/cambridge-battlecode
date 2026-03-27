from cambc import Controller, EntityType

from .Symmetry.TerrainMemory import SymmetryAnalyzer

def refresh_core_pos(
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


def ensure_symmetry_analyzer(
    ct: Controller,
    symmetry_analyzer: SymmetryAnalyzer | None,
    core_pos: tuple[int, int] | None,
) -> SymmetryAnalyzer:
    if symmetry_analyzer is None:
        return SymmetryAnalyzer(ct, core_pos=core_pos)
    if core_pos is not None:
        symmetry_analyzer.update_core_pos(core_pos)
    return symmetry_analyzer
