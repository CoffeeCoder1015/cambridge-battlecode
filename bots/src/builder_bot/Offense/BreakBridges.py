from cambc import Controller, EntityType, Position


class BreakBridges:
    def __init__(self, debug_prints: bool = False):
        self.debug_prints = debug_prints

    def is_enemy_core_visible(self, ct: Controller) -> bool:
        my_team = ct.get_team()
        for building_id in ct.get_nearby_buildings():
            try:
                if (
                    ct.get_entity_type(building_id) == EntityType.CORE
                    and ct.get_team(building_id) != my_team
                ):
                    return True
            except Exception:
                continue
        return False

    def select_bridge_target_with_stats(
        self, ct: Controller
    ) -> tuple[Position | None, int, int]:
        my_team = ct.get_team()
        my_id = ct.get_id()
        my_pos = ct.get_position()
        best_target: Position | None = None
        best_dist_sq: int | None = None

        total_enemy_bridges = 0
        occupied_enemy_bridges = 0

        for building_id in ct.get_nearby_buildings():
            try:
                if ct.get_entity_type(building_id) != EntityType.BRIDGE:
                    continue
                if ct.get_team(building_id) == my_team:
                    continue
                bridge_pos = ct.get_position(building_id)
            except Exception:
                continue

            total_enemy_bridges += 1

            bot_id = ct.get_tile_builder_bot_id(bridge_pos)
            if bot_id is not None and bot_id != my_id:
                occupied_enemy_bridges += 1
                continue

            dist_sq = my_pos.distance_squared(bridge_pos)
            if best_target is None or (best_dist_sq is not None and dist_sq < best_dist_sq):
                best_target = bridge_pos
                best_dist_sq = dist_sq

        return best_target, total_enemy_bridges, occupied_enemy_bridges

    def find_closest_open_enemy_bridge(self, ct: Controller) -> Position | None:
        target, _, _ = self.select_bridge_target_with_stats(ct)
        return target
