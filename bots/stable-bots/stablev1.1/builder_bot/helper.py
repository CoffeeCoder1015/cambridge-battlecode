from cambc import Controller, EntityType

from .Symmetry.TerrainMemory import SymmetryAnalyzer


def get_cost_affordability(
    ct: Controller,
    cost_getter_name: str,
) -> tuple[bool, tuple[int, int], tuple[int, int]]:
    available_resources = ct.get_global_resources()
    cost_getter = getattr(ct, cost_getter_name, None)
    if not callable(cost_getter):
        # Backward compatibility for environments missing the getter.
        return True, (0, 0), available_resources

    required_cost = cost_getter()
    affordable = (
        available_resources[0] >= required_cost[0]
        and available_resources[1] >= required_cost[1]
    )
    return affordable, required_cost, available_resources


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
