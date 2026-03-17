# Cambridge Battlecode — Game Reference

> API reference, types, constants, and entity data. This is the document to keep in context when writing bot logic.

---

## Table of Contents

1. [Bot Structure](#1-bot-structure)
2. [Controller API](#2-controller-api)
3. [Types & Enums](#3-types--enums)
4. [Game Constants](#4-game-constants)
5. [Entity Quick Reference](#5-entity-quick-reference)
6. [Match & Ladder Rules](#6-match--ladder-rules)

---

## 1. Bot Structure

```python
from cambc import *

class Player:
    def __init__(self):
        pass  # per-unit state; persists across rounds, not shared between units

    def run(self, c: Controller) -> None:
        pass  # called once per round per unit
```

- `from cambc import *` gives you: `Team`, `EntityType`, `ResourceType`, `Environment`, `Direction`, `Position`, `GameConstants`, `GameError`, `Controller`
- One `Player` instance per unit — state does **not** cross unit boundaries
- Use `c.get_entity_type()` to branch on what kind of unit you are
- Use **markers** for inter-unit communication
- **2ms CPU time limit** per unit per round (+ 5% refilling buffer)

---

## 2. Controller API

The `Controller` (`c`) is the sole interface to the game engine. Passed to `run()` every round.

### Unit Info

| Method | Returns | Description |
|--------|---------|-------------|
| `get_team(id=None)` | `Team` | Team of entity `id`, or this unit |
| `get_position(id=None)` | `Position` | Position of entity `id`, or this unit |
| `get_id()` | `int` | This unit's entity id |
| `get_action_cooldown()` | `int` | Current action cooldown; actions require 0 |
| `get_move_cooldown()` | `int` | Current move cooldown; movement requires 0 |
| `get_hp(id=None)` | `int` | Current HP of entity `id`, or this unit |
| `get_max_hp(id=None)` | `int` | Max HP of entity `id`, or this unit |
| `get_entity_type(id=None)` | `EntityType` | EntityType of entity `id`, or this unit |
| `get_direction(id=None)` | `Direction` | Facing direction of a conveyor/splitter/armoured conveyor/turret. Raises `GameError` if entity has no direction |
| `get_vision_radius_sq(id=None)` | `int` | Vision radius² of entity `id`, or this unit |

### Turret Info

| Method | Returns | Description |
|--------|---------|-------------|
| `get_ammo_amount()` | `int` | Amount of ammo this turret holds |
| `get_ammo_type()` | `ResourceType \| None` | Resource type loaded as ammo, or None if empty |
| `get_gunner_target()` | `Position \| None` | Closest non-empty tile in gunner's facing direction, or None. Gunners only |

### Building Info

| Method | Returns | Description |
|--------|---------|-------------|
| `get_bridge_target(id: int)` | `Position` | Output target of a bridge. Raises `GameError` if not a bridge |
| `get_stored_resource(id=None)` | `ResourceType \| None` | Resource in a conveyor/splitter/armoured conveyor/bridge/foundry. Raises `GameError` if entity has no storage |

### Tile Queries

| Method | Returns | Description |
|--------|---------|-------------|
| `get_tile_env(pos)` | `Environment` | Environment type at pos (empty, wall, ore) |
| `get_tile_building_id(pos)` | `int \| None` | Id of building at pos, or None |
| `get_tile_builder_bot_id(pos)` | `int \| None` | Id of builder bot at pos, or None |
| `is_tile_empty(pos)` | `bool` | True if no building and not a wall |
| `is_tile_passable(pos)` | `bool` | True if a friendly builder bot could stand here (conveyor, road, or allied core; no other bot) |
| `is_in_vision(pos)` | `bool` | True if pos is within this unit's vision radius |

### Nearby Queries

`dist_sq` defaults to vision radius; must not exceed it.

| Method | Returns | Description |
|--------|---------|-------------|
| `get_nearby_tiles(dist_sq=None)` | `list[Position]` | All in-bounds positions within dist_sq |
| `get_nearby_entities(dist_sq=None)` | `list[int]` | Ids of all entities within dist_sq |
| `get_nearby_buildings(dist_sq=None)` | `list[int]` | Ids of all buildings within dist_sq |
| `get_nearby_units(dist_sq=None)` | `list[int]` | Ids of all units within dist_sq |

### Map & Game State

| Method | Returns | Description |
|--------|---------|-------------|
| `get_map_width()` | `int` | Map width in tiles |
| `get_map_height()` | `int` | Map height in tiles |
| `get_current_round()` | `int` | Current round number (starts at 1) |
| `get_global_resources()` | `tuple[int, int]` | `(titanium, axionite)` in team's resource pool |
| `get_scale_percent()` | `float` | Current cost scale as % (100.0 = base cost) |
| `get_cpu_time_elapsed()` | `int` | CPU time used this round, in microseconds |

### Cost Getters

All return current scaled `(titanium, axionite)`:

```python
c.get_builder_bot_cost()
c.get_conveyor_cost()
c.get_splitter_cost()
c.get_bridge_cost()
c.get_armoured_conveyor_cost()
c.get_harvester_cost()
c.get_road_cost()
c.get_barrier_cost()
c.get_foundry_cost()
c.get_gunner_cost()
c.get_sentinel_cost()
c.get_breach_cost()
c.get_launcher_cost()
```

### Movement

Builder bots only.

| Method | Returns | Description |
|--------|---------|-------------|
| `move(direction)` | `None` | Move one step. Raises `GameError` if not legal |
| `can_move(direction)` | `bool` | True if move is legal this round |

### Building

All build actions require action cooldown == 0 and sufficient resources. `can_build_*` returns `bool`; `build_*` raises `GameError` if not legal.

**Directional** — take `(pos: Position, direction: Direction)`:

```python
c.build_conveyor(pos, direction)           c.can_build_conveyor(pos, direction)
c.build_splitter(pos, direction)           c.can_build_splitter(pos, direction)
c.build_armoured_conveyor(pos, direction)  c.can_build_armoured_conveyor(pos, direction)
c.build_gunner(pos, direction)             c.can_build_gunner(pos, direction)
c.build_sentinel(pos, direction)           c.can_build_sentinel(pos, direction)
c.build_breach(pos, direction)             c.can_build_breach(pos, direction)
```

**Bridge** — takes `(pos: Position, target: Position)`, target within dist²=9:

```python
c.build_bridge(pos, target)                c.can_build_bridge(pos, target)
```

**Non-directional** — take `(pos: Position)`:

```python
c.build_harvester(pos)                     c.can_build_harvester(pos)
c.build_road(pos)                          c.can_build_road(pos)
c.build_barrier(pos)                       c.can_build_barrier(pos)
c.build_foundry(pos)                       c.can_build_foundry(pos)
c.build_launcher(pos)                      c.can_build_launcher(pos)
```

### Healing & Destruction

| Method | Returns | Description |
|--------|---------|-------------|
| `heal(position)` | `None` | Heal all friendly entities on tile by 10 HP. Costs one action cooldown |
| `can_heal(position)` | `bool` | True if heal is legal this round |
| `destroy(building_pos)` | `None` | Destroy an allied building. Does **not** cost action cooldown |
| `can_destroy(building_pos)` | `bool` | True if destroy is legal |
| `self_destruct()` | `None` | Destroy this unit. Builder bots deal 20 damage to their tile |

### Markers

No action cooldown cost. Max one placement per round. Used for inter-unit communication.

| Method | Returns | Description |
|--------|---------|-------------|
| `place_marker(position, value: int)` | `None` | Place marker with u32 value |
| `can_place_marker(position)` | `bool` | True if placement is legal |
| `get_marker_value(id: int)` | `int` | u32 value stored in friendly marker |

### Combat

| Method | Returns | Description |
|--------|---------|-------------|
| `fire(target)` | `None` | Fire this turret at target. Use `launch()` for launchers |
| `can_fire(target)` | `bool` | True if fire is legal this round |
| `launch(bot_pos, target)` | `None` | Pick up builder bot at bot_pos and throw to target |
| `can_launch(bot_pos, target)` | `bool` | True if launch is legal |

### Core

| Method | Returns | Description |
|--------|---------|-------------|
| `spawn_builder(position)` | `None` | Spawn a builder bot on one of the 9 core tiles. Costs one action cooldown |
| `can_spawn(position)` | `bool` | True if spawn is legal this round |

### Debug Indicators

Saved to replay; visible in the visualiser.

| Method | Description |
|--------|-------------|
| `draw_indicator_line(pos_a, pos_b, r, g, b)` | Debug line between two positions with RGB colour |
| `draw_indicator_dot(pos, r, g, b)` | Debug dot at position with RGB colour |

---

## 3. Types & Enums

### Team

```python
class Team(Enum):
    A = "a"
    B = "b"
```

### EntityType

```python
class EntityType(Enum):
    BUILDER_BOT       = "builder_bot"
    CORE              = "core"
    GUNNER            = "gunner"
    SENTINEL          = "sentinel"
    BREACH            = "breach"
    LAUNCHER          = "launcher"
    CONVEYOR          = "conveyor"
    SPLITTER          = "splitter"
    ARMOURED_CONVEYOR = "armoured_conveyor"
    BRIDGE            = "bridge"
    HARVESTER         = "harvester"
    FOUNDRY           = "foundry"
    ROAD              = "road"
    BARRIER           = "barrier"
    MARKER            = "marker"
```

### ResourceType

```python
class ResourceType(Enum):
    TITANIUM         = "titanium"
    RAW_AXIONITE     = "raw_axionite"
    REFINED_AXIONITE = "refined_axionite"
```

### Environment

```python
class Environment(Enum):
    EMPTY        = "empty"
    WALL         = "wall"
    ORE_TITANIUM = "ore_titanium"
    ORE_AXIONITE = "ore_axionite"
```

### Direction

```python
class Direction(Enum):
    NORTH     = "north"      # (0, -1)
    NORTHEAST = "northeast"  # (1, -1)
    EAST      = "east"       # (1, 0)
    SOUTHEAST = "southeast"  # (1, 1)
    SOUTH     = "south"      # (0, 1)
    SOUTHWEST = "southwest"  # (-1, 1)
    WEST      = "west"       # (-1, 0)
    NORTHWEST = "northwest"  # (-1, -1)
    CENTRE    = "centre"     # (0, 0)
```

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `delta()` | `tuple[int, int]` | `(dx, dy)` step for this direction |
| `rotate_left()` | `Direction` | Rotated 45° counterclockwise |
| `rotate_right()` | `Direction` | Rotated 45° clockwise |
| `opposite()` | `Direction` | Opposite direction (180°) |

### Position

```python
class Position(NamedTuple):
    x: int
    y: int
```

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `add(direction)` | `Position` | New position offset by direction delta |
| `distance_squared(other)` | `int` | Squared Euclidean distance to other |
| `direction_to(other)` | `Direction` | Closest 45° direction approximation toward other |

```python
pos = Position(5, 10)
pos.add(Direction.NORTH)          # Position(5, 9)
pos.distance_squared(Position(5, 9))  # 1
pos.direction_to(Position(8, 7))  # Direction.NORTHEAST
```

### GameError

```python
class GameError(Exception):
    pass
```

Raised on any invalid action (building on occupied tile, moving with cooldown > 0, etc.).

---

## 4. Game Constants

```python
from cambc import GameConstants
GameConstants.MAX_TURNS  # 2000
```

### General

| Constant | Value | Description |
|----------|-------|-------------|
| `MAX_TURNS` | 2000 | Maximum turns per game |
| `STACK_SIZE` | 10 | Resources moved in stacks of 10 |
| `STARTING_TITANIUM` | 1000 | Each team's initial titanium |
| `STARTING_AXIONITE` | 0 | Each team's initial axionite |

### Radii (squared)

| Constant | Value | Description |
|----------|-------|-------------|
| `ACTION_RADIUS_SQ` | 2 | Default action radius |
| `CORE_ACTION_RADIUS_SQ` | 8 | Core action radius (from centre) |
| `CORE_SPAWNING_RADIUS_SQ` | 2 | Core spawning radius |
| `CORE_VISION_RADIUS_SQ` | 36 | Core vision |
| `BUILDER_BOT_VISION_RADIUS_SQ` | 20 | Builder bot vision |
| `GUNNER_VISION_RADIUS_SQ` | 13 | Gunner vision |
| `SENTINEL_VISION_RADIUS_SQ` | 32 | Sentinel vision |
| `BREACH_VISION_RADIUS_SQ` | 10 | Breach vision |
| `BREACH_ATTACK_RADIUS_SQ` | 5 | Breach attack cone |
| `LAUNCHER_VISION_RADIUS_SQ` | 26 | Launcher vision + throw range |
| `BRIDGE_TARGET_RADIUS_SQ` | 9 | Max bridge output distance² |

### Base Costs (titanium, axionite)

| Constant | Value |
|----------|-------|
| `BUILDER_BOT_BASE_COST` | (10, 0) |
| `CONVEYOR_BASE_COST` | (3, 0) |
| `SPLITTER_BASE_COST` | (6, 0) |
| `BRIDGE_BASE_COST` | (10, 0) |
| `ARMOURED_CONVEYOR_BASE_COST` | (10, 5) |
| `HARVESTER_BASE_COST` | (80, 0) |
| `ROAD_BASE_COST` | (1, 0) |
| `BARRIER_BASE_COST` | (3, 0) |
| `FOUNDRY_BASE_COST` | (120, 0) |
| `GUNNER_BASE_COST` | (10, 0) |
| `SENTINEL_BASE_COST` | (15, 0) |
| `BREACH_BASE_COST` | (30, 10) |
| `LAUNCHER_BASE_COST` | (20, 0) |

### Max HP

| Constant | Value |
|----------|-------|
| `CORE_MAX_HP` | 500 |
| `BUILDER_BOT_MAX_HP` | 30 |
| `CONVEYOR_MAX_HP` | 20 |
| `SPLITTER_MAX_HP` | 20 |
| `BRIDGE_MAX_HP` | 20 |
| `ARMOURED_CONVEYOR_MAX_HP` | 50 |
| `HARVESTER_MAX_HP` | 30 |
| `ROAD_MAX_HP` | 10 |
| `BARRIER_MAX_HP` | 30 |
| `FOUNDRY_MAX_HP` | 50 |
| `MARKER_MAX_HP` | 1 |
| `GUNNER_MAX_HP` | 40 |
| `SENTINEL_MAX_HP` | 30 |
| `BREACH_MAX_HP` | 60 |
| `LAUNCHER_MAX_HP` | 30 |

### Combat Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `BUILDER_BOT_SELF_DESTRUCT_DAMAGE` | 20 | Damage on self-destruct |
| `HEAL_AMOUNT` | 10 | HP restored per heal action |
| `GUNNER_DAMAGE` | 10 | Damage per shot |
| `GUNNER_FIRE_COOLDOWN` | 1 | Turns between shots |
| `GUNNER_AMMO_COST` | 2 | Resources per shot |
| `SENTINEL_DAMAGE` | 20 | Damage per shot |
| `SENTINEL_FIRE_COOLDOWN` | 4 | Turns between shots |
| `SENTINEL_AMMO_COST` | 10 | Resources per shot |
| `BREACH_DAMAGE` | 40 | Direct hit damage |
| `BREACH_SPLASH_DAMAGE` | 20 | Splash damage |
| `BREACH_FIRE_COOLDOWN` | 1 | Turns between shots |
| `BREACH_AMMO_COST` | 5 | Refined axionite per shot |
| `LAUNCHER_FIRE_COOLDOWN` | 1 | Turns between throws |

---

## 5. Entity Quick Reference

### Units

| Entity | HP | Cost (Ti, Ax) | Vision R² | Notes |
|--------|----|---------------|-----------|-------|
| Core | 500 | — | 36 | Spawns builder bots; loss = game over |
| Builder Bot | 30 | (10, 0) | 20 | Only mobile unit; builds all structures |

### Turrets

| Entity | HP | Cost (Ti, Ax) | Vision R² | Damage | Cooldown | Ammo Cost | Notes |
|--------|----|---------------|-----------|--------|----------|-----------|-------|
| Gunner | 40 | (10, 0) | 13 | 10 | 1 | 2 | Fires in facing direction |
| Sentinel | 30 | (15, 0) | 32 | 20 | 4 | 10 | High vision, slower fire rate |
| Breach | 60 | (30, 10) | 10 | 40 / 20 splash | 1 | 5 refined axionite | Splash damage |
| Launcher | 30 | (20, 0) | 26 | — | 1 | — | Throws builder bots |

### Infrastructure

| Entity | HP | Cost (Ti, Ax) | Directional | Notes |
|--------|----|---------------|-------------|-------|
| Conveyor | 20 | (3, 0) | Yes | Moves resources along network |
| Splitter | 20 | (6, 0) | Yes | Splits resource flow |
| Armoured Conveyor | 50 | (10, 5) | Yes | Higher HP; harder to destroy |
| Bridge | 20 | (10, 0) | No (target) | Teleports resources; target within dist²=9 |
| Harvester | 30 | (80, 0) | No | Must be placed on an ore tile |
| Foundry | 50 | (120, 0) | No | Refines raw axionite → refined axionite |
| Road | 10 | (1, 0) | No | Passable tile for builder bots |
| Barrier | 30 | (3, 0) | No | Blocks movement |
| Marker | 1 | — | No | Stores u32; used for inter-unit comms |

### Resources

| Resource | Description |
|----------|-------------|
| Titanium | Primary currency; mined from `ORE_TITANIUM` tiles via harvesters |
| Raw Axionite | Mined from `ORE_AXIONITE` tiles; must be processed by a Foundry |
| Refined Axionite | Output of Foundry; required for armoured conveyors, breach ammo, and advanced builds |

---

---

## 6. Match & Ladder Rules

### Match Format

Each ladder match = **5 games**, each on a different map with a different seed. The team that wins more games wins the match.

### Win Conditions per Game

| Condition | Description |
|-----------|-------------|
| **Core destroyed** | One team's core reaches 0 HP |
| **Resources** | After 2000 rounds, tiebreaker sequence determines winner |
| **Timeout** | Equal tiebreakers after 2000 rounds — coinflip |

### Ladder & Rating

- Ranked by **Glicko-2**; new teams seeded at **1500**
- Scheduler runs every **10 minutes**: pairs each team with a similarly-rated opponent (greedy nearest-rating with jitter), avoids rematches from the last hour
- Ratings use fractional scoring — a 5-0 win counts more than a 3-2 win
- Three rating components: **Rating** (skill estimate), **Uncertainty/RD** (confidence, starts high), **Volatility** (expected fluctuation)

### Unrated Matches

Same infrastructure and time limits as ladder matches, no rating impact, prioritised for faster execution.

```bash
cambc unrated <opponent_team_id>
cambc unrated <opponent_team_id> --match <source_match_id>   # use opponent's version from a past match
```

---

*Note: The official Game Rules section (`/spec/*`) was unavailable at crawl time (competition launched March 16, 2026, pages not yet indexed). All API, type, and constant data above is sourced directly from the live documentation.*