from cambc import Controller, EntityType


def refresh_core_pos(
    ct: Controller,
    current_core_pos: tuple[int, int] | None,
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
    return current_core_pos


def set_nav_target(
    nav,
    last_nav_target: tuple[int, int] | None,
    tx: int,
    ty: int,
) -> tuple[tuple[int, int], bool]:
    next_target = (tx, ty)
    if last_nav_target != next_target:
        nav.set_target(tx, ty)
    return next_target, True


def execute_nav_step(ct: Controller, nav) -> bool:
    move_dir = nav.next_move(ct)
    if move_dir is None:
        return False

    acted = False
    move_pos = ct.get_position().add(move_dir)
    if not ct.is_tile_passable(move_pos):
        has_friendly_marker = any(
            ct.get_entity_type(eid) == EntityType.MARKER
            and ct.get_team(eid) == ct.get_team()
            and ct.get_position(eid) == move_pos
            for eid in ct.get_nearby_entities()
        )
        if ct.can_build_road(move_pos) and not has_friendly_marker:
            ct.build_road(move_pos)
            acted = True

    if ct.can_move(move_dir):
        ct.move(move_dir)
        acted = True

    return acted
