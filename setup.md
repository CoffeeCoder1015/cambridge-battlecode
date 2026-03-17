# Cambridge Battlecode — Practical Guide

> Installation, CLI usage, running matches, and submitting. This document covers the **how** — set it aside once your environment is working.

---

## Table of Contents

1. [Installation](#1-installation)
2. [Running Matches](#2-running-matches)
3. [Submitting](#3-submitting)
4. [CLI Reference](#4-cli-reference)

---

## 1. Installation

### Requirements

- **Python 3.12+**
- **pip** (comes with Python)

### Install

```bash
pip install cambc
```

Includes the CLI tool and the compiled Rust game engine as a native Python module. No Docker, Rust toolchain, or Node.js required.

Supported platforms: macOS (Apple Silicon + Intel), Linux (x86_64 + ARM64), Windows (x86_64).

### Verify

```bash
cambc --version
```

### Set up your project

```bash
cambc starter
```

Scaffolds a project with a `cambc.toml` config, `bots/` and `maps/` directories, a `.gitignore`, and optionally a starter bot.

### What's Included

| Component | Description |
|-----------|-------------|
| `cambc` CLI | Run local matches, open the visualiser, submit bots, trigger test runs |
| `cambc` Python module | Game types (`Team`, `EntityType`, `Direction`, `Position`, etc.) |
| `titan_runner` | The compiled Rust game engine (embedded, runs locally with no time limits) |

---

## 2. Running Matches

### Local match

```bash
cambc run <bot_a> <bot_b> [map]
```

No time limits enforced. Outputs `replay.replay26`.

```bash
cambc run starter starter                        # bot vs itself
cambc run my_bot opponent --seed 42              # deterministic seed
cambc run my_bot opponent maps/custom.map26      # custom map
cambc run my_bot opponent --replay out.replay26  # custom replay path
cambc run --watch my_bot opponent                # run + auto-open visualiser
```

### View a replay

```bash
cambc watch replay.replay26
cambc watch --match <match_id>
cambc watch --match <match_id> --game 3
```

### Remote test runs

Runs on the same AWS Graviton3 hardware as the ladder, with the 2ms time limit enforced.

```bash
cambc login                                       # authenticate first
cambc test-run my_bot opponent
cambc test-run my_bot opponent maps/custom.map26
```

Bot paths must be a directory containing `main.py` or a `.zip` (not bare `.py` files).

**Rate limits:** max 10 test/unrated matches per 5 minutes.

### Debugging

- `print()` → captured to replay, viewable per-unit in the visualiser
- `stderr` → prints to console in real time
- `c.draw_indicator_line(pos_a, pos_b, r, g, b)` → debug overlay line
- `c.draw_indicator_dot(pos, r, g, b)` → debug overlay dot

---

## 3. Submitting

### Authenticate

```bash
cambc login    # opens OAuth in browser
cambc logout   # clear credentials
```

### Submit

```bash
cambc submit ./my_bot/    # directory (auto-zipped)
cambc submit my_bot.py    # single file
cambc submit my_bot.zip   # pre-zipped
```

Or go to [game.battlecode.cam](https://game.battlecode.cam) → **Submissions** → upload zip.

### Bot Requirements

| Constraint | Limit |
|------------|-------|
| Zip size | 5 MB max |
| Decompressed size | 50 MB max |
| File count | 500 files max |
| Native extensions | **Not allowed** (`.so`, `.pyd`, `.dylib`, `.dll`) |
| Imports | Must be top-level — file I/O is blocked during `run()` |

- Must contain a `main.py` with a `Player` class
- File can be at zip root or inside one top-level directory

### After Upload

1. Zip validated (structure, size, no native extensions)
2. Status → **ready**
3. Latest ready submission becomes your active ladder bot
4. Scheduler pairs you against opponents every 10 minutes

---

## 4. CLI Reference

### Project setup

#### `cambc starter`

```bash
cambc starter
```

Creates:
```
your-project/
├── cambc.toml
├── .gitignore
├── bots/
│   └── starter/
│       └── main.py
└── maps/
```

#### `cambc.toml`

```toml
bots_dir = "bots"
maps_dir = "maps"
replay = "replay.replay26"
seed = 1
```

Bot paths resolve first by raw path, then by looking inside `bots_dir`.

---

### Local development

#### `cambc run`

```bash
cambc run <bot_a> <bot_b> [map]
```

| Argument | Description |
|----------|-------------|
| `bot_a` | Directory with `main.py`, a `.py` file, or name in `bots_dir` |
| `bot_b` | Same formats |
| `map` | Optional `.map26` file; defaults to first in `maps_dir` |

| Option | Description |
|--------|-------------|
| `--replay PATH` | Output replay path |
| `--seed N` | Map seed |
| `--watch` | Auto-open visualiser after match |

#### `cambc watch`

```bash
cambc watch replay.replay26
cambc watch --match <match_id>
cambc watch --match <match_id> --game <n>
```

#### `cambc map-editor`

```bash
cambc map-editor
cambc map-editor --platform
```

---

### Platform commands

#### `cambc login` / `cambc logout`

```bash
cambc login
cambc logout
```

#### `cambc submit`

```bash
cambc submit <path>    # directory, .py, or .zip
```

#### `cambc status`

```bash
cambc status
```

Shows username, team, Glicko-2 rating + uncertainty, matches played, members.

#### `cambc unrated`

```bash
cambc unrated <opponent_team_id>
cambc unrated <opponent_team_id> --match <source_match_id>
```

#### `cambc test-run`

```bash
cambc test-run <bot_a> <bot_b> [map]
```

#### `cambc matches`

```bash
cambc matches [--type {ladder|unrated}] [--team NAME] [--limit N] [--cursor CURSOR]
```

#### `cambc match`

```bash
cambc match <match_id>
```

#### `cambc test-matches`

```bash
cambc test-matches [--limit N]
```

#### `cambc teams`

```bash
cambc teams search <query>
cambc teams info <team_id>
```