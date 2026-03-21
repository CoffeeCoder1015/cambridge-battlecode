import random
import sys
from cambc import Controller, Direction, EntityType

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

MAGIC_MASK = 0x5A000000
INFO_MASK  = 0x00000007

# Mapping from 2-bit eliminated mask to the surviving symmetry code
_MASK_TO_SYM = {
    0b110: 101,  # REF_Y + ROT eliminated -> REF_X survives
    0b101: 102,  # REF_X + ROT eliminated -> REF_Y survives
    0b011: 103,  # REF_X + REF_Y eliminated -> ROT survives
}
_SYM_NAMES = {101: "REF_X", 102: "REF_Y", 103: "ROT"}


class Core:
    def __init__(self):
        self.solved_sym: int | None = None

    def run(self, ct: Controller, player) -> None:
        if player.num_spawned < 100:
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                player.num_spawned += 1

        '''
        SYMMETRY SCAN NEARBY MARKERS
        '''
        if self.solved_sym is None and ct.get_current_round() % 2 == 0:
            combined_mask = 0
            for m_id in ct.get_nearby_entities():
                try:
                    if (ct.get_entity_type(m_id) == EntityType.MARKER
                            and ct.get_team(m_id) == ct.get_team()):
                        val = ct.get_marker_value(m_id)
                        if isinstance(val, int) and (val & 0xFF000000) == MAGIC_MASK:
                            combined_mask |= val & INFO_MASK
                except Exception:
                    continue

            sym = _MASK_TO_SYM.get(combined_mask)
            if sym is not None:
                self.solved_sym = sym
                print(
                    f"TURN {ct.get_current_round()}: [Core {ct.get_position()}] "
                    f"CORE HAS RESOLVED SYMMETRY -> {_SYM_NAMES[sym]}",
                    file=sys.stderr,
                )

