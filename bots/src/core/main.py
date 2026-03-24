from collections import deque

from cambc import Controller, Direction, EntityType

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

MAGIC_MASK = 0x5A000000
INFO_MASK = 0x00000007

_MASK_TO_SYM = {
    0b110: 101,
    0b101: 102,
    0b011: 103,
}
_SYM_NAMES = {101: "REF_X", 102: "REF_Y", 103: "ROT"}


class Core:
    def __init__(self):
        self.solved_sym: int | None = None

        self.spawned = 0
        self.reinvestment_budget = 0
        self.last_titanium = 0

        self.growth_history = deque(maxlen=25)
        self.sum_x = 0
        self.sum_x2 = 0
        self.moving_avg_growth = 0
        self.variance = 0

        self.pairs = [(0, 4), (2, 6), (1, 5), (3, 7)]
        self.reserve_buffer = 120

    def run(self, ct: Controller, player) -> None:
        res = ct.get_global_resources()
        titanium = res[0]
        rnd = ct.get_current_round()

        if rnd > 1 and titanium < 3:
            self.reserve_buffer += 50
        elif rnd > 1 and titanium > self.reserve_buffer + 100:
            self.reserve_buffer = max(120, self.reserve_buffer - 1)

        if rnd > 0:
            delta = max(0, titanium - self.last_titanium)

            if len(self.growth_history) == 25:
                old_x = self.growth_history[0]
                self.sum_x -= old_x
                self.sum_x2 -= old_x**2

            self.growth_history.append(delta)
            self.sum_x += delta
            self.sum_x2 += delta**2

            count = len(self.growth_history)
            if count > 0:
                self.moving_avg_growth = self.sum_x / count
                self.variance = max(
                    0, (self.sum_x2 / count) - (self.moving_avg_growth**2)
                )

            if self.moving_avg_growth >= 1.2:
                self.reinvestment_budget += self.moving_avg_growth * 0.8

        harv_c_early = ct.get_harvester_cost()[0]
        conv_c_early = ct.get_conveyor_cost()[0]
        min_reserve = harv_c_early + 3 * conv_c_early
        self.reserve_buffer = max(self.reserve_buffer, min_reserve)

        self.last_titanium = titanium

        if ct.get_action_cooldown() == 0:
            if rnd < 60:
                bot_c = ct.get_builder_bot_cost()[0]
                if self.spawned < 4 and titanium >= bot_c:
                    self._spawn(ct)
                return

            bot_c = ct.get_builder_bot_cost()[0]
            harv_c = ct.get_harvester_cost()[0]
            conv_c = ct.get_conveyor_cost()[0]
            current_deployment_cost = bot_c + harv_c + conv_c

            current_scale = getattr(ct, "get_scale_percent", lambda: 100.0)()
            scale_penalty = (current_scale - 100.0) * 0.05
            wealth_bonus = (titanium / 500) * 0.10

            margin_pct = 0.10 - scale_penalty - wealth_bonus
            margin_pct = max(-1.50, min(0.20, margin_pct))

            target_budget = current_deployment_cost * (1.0 + margin_pct)

            wealth_overdrive = titanium > self.reserve_buffer * 3

            if (
                self.reinvestment_budget >= target_budget or wealth_overdrive
            ) and titanium >= self.reserve_buffer + bot_c:
                self._spawn(ct)
                self.reinvestment_budget -= current_deployment_cost

        if self.solved_sym is None and ct.get_current_round() % 2 == 0:
            combined_mask = 0
            for m_id in ct.get_nearby_entities():
                try:
                    if (
                        ct.get_entity_type(m_id) == EntityType.MARKER
                        and ct.get_team(m_id) == ct.get_team()
                    ):
                        val = ct.get_marker_value(m_id)
                        if isinstance(val, int) and (val & 0xFF000000) == MAGIC_MASK:
                            combined_mask |= val & INFO_MASK
                except Exception:
                    continue

            sym = _MASK_TO_SYM.get(combined_mask)
            if sym is not None:
                self.solved_sym = sym

    def _spawn(self, ct: Controller):
        pair_idx = (self.spawned // 2) % 4
        sub_idx = self.spawned % 2
        preferred_d_idx = self.pairs[pair_idx][sub_idx]

        for offset in range(8):
            d_idx = (preferred_d_idx + offset) % 8
            d = DIRECTIONS[d_idx]
            spawn_pos = ct.get_position().add(d)

            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.spawned += 1
                return
