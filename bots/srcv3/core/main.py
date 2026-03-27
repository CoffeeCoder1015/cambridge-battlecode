from cambc import Controller, Direction, Position


_MAX_BUILDER_BOTS = 3


class Core:
    def __init__(self) -> None:
        self._spawned_bots = 0

    def run(self, ct: Controller) -> None:
        if ct.get_action_cooldown() > 0:
            return
        if self._spawned_bots >= _MAX_BUILDER_BOTS:
            return

        my_pos = ct.get_position()
        mid = Position(ct.get_map_width() // 2, ct.get_map_height() // 2)
        base = my_pos.direction_to(mid)
        candidate_dirs = (
            base,
            base.rotate_right(),
            base.rotate_left(),
            base.rotate_right().rotate_right(),
            base.rotate_left().rotate_left(),
            base.rotate_right().rotate_right().rotate_right(),
            base.rotate_left().rotate_left().rotate_left(),
            base.opposite(),
        )

        for d in candidate_dirs:
            if d == Direction.CENTRE:
                continue
            spawn_pos = my_pos.add(d)
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self._spawned_bots += 1
                return
