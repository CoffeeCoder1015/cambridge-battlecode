# Cambridge Battlecode

This repository preserves notable problem-solving ideas explored during
Cambridge Battlecode 2026. Different directories contain different experiments,
and not every idea was active at the same time.

## Highlights

### Bucketed A*

Typical A* implementations use a min-heap priority queue, which incurs a massive
bottleneck on Battlecode bots with a strict 2 ms runtime per move. A key
realization was that movement occurs on a grid with equal costs in all eight
directions. This allows integer heuristic scores, meaning a bucketed priority
queue can massively speed up the search.

[Implementation](bots/k_learning/builderbot/navigation.py#L249)

### Supply-line hijacking

Supply systems do not distinguish friendly and enemy infrastructure when passing
resources, making ownership less important than routing. Instead of destroying
an enemy harvester, bridges can redirect its output into a friendly supply line,
simultaneously denying the opponent's income and reusing their production.

[Hijacking implementation](bots/src-q/builder_bot/BridgeBuilding/BridgeBuilder.py#L132) ·
[Supply-line tracing](bots/src-q/builder_bot/Movement/Hound.py#L443)

### Symmetry elimination

Map symmetry turns locating the opposing core from a search problem into a
process of elimination. Every mirrored terrain mismatch rejects horizontal,
vertical, or rotational symmetry, while three marker bits allow builders to
share rejected candidates. Once one possibility remains, the opposing core
position follows directly.

[Implementation](bots/src/builder_bot/Symmetry/TerrainMemory.py#L87)

### Frontier exploration

Pathfinding decides how to reach a destination, but not where exploration should
continue. Growing new targets from reached positions, ranking them by distance
and age, and penalising inaccessible targets produces expanding, spiral-like
coverage with fewer repeated visits.

[Implementation](bots/k_learning/builderbot/navigation.py#L538)

### Bug navigation

Bug navigation provides a cheap alternative when the known map is too incomplete
for a global search. Direct movement and obstacle-boundary following handle the
route locally, while trail memory and recovery behaviour prevent those local
decisions from repeating the same loop indefinitely.

[Implementation](bots/src-q/builder_bot/Movement/TangentBug.py#L125)

### Resumable construction

Construction sequences span several turns, so their unfinished intent must
survive cooldowns, movement, and temporary resource shortages. Recording the
active phase turns conveyor and bridge construction into resumable plans instead
of forcing each turn to reconstruct the job from the surrounding map.

[Guarded conveyor implementation](bots/src/builder_bot/GuardedConveyer/GuardedConveyer.py#L27) ·
[Bridge-building implementation](bots/src/builder_bot/BridgeBuilding/BridgeBuilder.py#L39)

### Adaptive spending

Fixed spawn timings ignore whether the economy can support further expansion. A
rolling income estimate funds reinvestment, while a dynamic reserve protects the
next resource line. Resource starvation raises the reserve, while sustained
surplus permits more aggressive spending.

[Implementation](bots/src/core/main.py#L35)

## Repository map

| Directory | Main ideas preserved |
| --- | --- |
| `bots/k_learning` | Bucketed A*, bounded search, frontier exploration, and local symmetry inference |
| `bots/src-q` | Supply hijacking, offensive routing, navigation, and integrated strategy experiments |
| `bots/src` | Shared symmetry deductions, resumable infrastructure, and adaptive spending |
| `bots/srcv2` | Intermediate navigation and infrastructure work |
| `bots/stable-bots` | Preserved stable snapshots |
| `bots/q_learning`, `bots/ql_old` | Earlier economy and strategy experiments |
| `bots/starter`, `bots/do_nothing` | Reference and baseline bots |

The `q_learning` and `k_learning` names are historical. These directories do not
contain a trained reinforcement-learning model or Q-table.

## Running a match

```bash
pip install cambc
cambc run k_learning src-q
```

See the [setup guide](setup.md) for full commands and the
[game reference](docs.md) for the Controller API.
