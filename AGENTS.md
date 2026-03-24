# Cambridge Battlecode Agent Guidelines

Welcome, AI Coding Agents! This document provides crucial context, commands, and conventions for operating within the Cambridge Battlecode Python repository. Read carefully before making modifications or implementing new bots.

---

## 1. Build, Lint, and Test Commands

Unlike traditional web projects, this repository does not use `pytest` or a standard unit testing framework. "Testing" in Battlecode consists of running your bot against other bots or itself on various maps. 

### Running Matches (Testing)

The `cambc` CLI is the primary tool for testing. 
- **Run a Local Match:** (No time limit, generates a replay)
  ```bash
  cambc run <bot_a> <bot_b> [map]
  ```
  *Examples:* 
  `cambc run starter starter` (bot vs itself)
  `cambc run my_bot opponent --seed 42` (deterministic seed)
  `cambc run my_bot opponent maps/custom.map26` (run on a specific custom map)
- **Watch a Replay:**
  ```bash
  cambc watch replay.replay26
  ```
- **Run + Auto-open Visualiser:**
  ```bash
  cambc run --watch my_bot opponent
  ```

### Remote Test Runs (Strict Enforcement)

Local matches do NOT enforce the 2ms time limit. To ensure your bot won't time out in the actual tournament, use `test-run`. This runs on AWS hardware matching the official ladder.
- **Run a Remote Test Match:**
  ```bash
  cambc test-run my_bot opponent
  ```
  *(Note: Rate limited to 10 matches per 5 minutes. Requires running `cambc login` once first).*

### Linting & Formatting

This project uses `ruff` (indicated by `.ruff_cache`) for fast linting and formatting. Always format your code before committing.
- **Check for Lint Errors:** 
  ```bash
  ruff check .
  ```
- **Auto-Fix Lint Errors:** 
  ```bash
  ruff check . --fix
  ```
- **Format Code:** 
  ```bash
  ruff format .
  ```

### Submitting

Once a bot is ready for the tournament ladder:
- **Submit Directory:** `cambc submit ./bots/my_bot/` (auto-zips and uploads)
- **Submit Zip:** `cambc submit my_bot.zip`

---

## 2. Code Style & Conventions

Adhere to the following conventions to ensure high-performance, compliant, and readable bots.

### Architecture & Engine Rules

1. **Entry Point:** Every bot must be housed in its own directory (e.g., `bots/my_bot/`) and MUST contain a `main.py` file defining a `Player` class.
2. **The `run` Method:** The engine instantiates `Player` once per unit. Every round the unit is alive, the engine calls `def run(self, ct: Controller) -> None:`.
3. **No File I/O:** File operations (read/write) are strictly blocked during the `run()` loop. Do not attempt to read config files dynamically.
4. **Top-Level Imports:** All imports MUST be at the top level. Dynamic `import()` calls inside functions will fail due to the file I/O block.
5. **No Native Extensions:** Python native extensions (`.so`, `.pyd`, `.dll`) are strictly prohibited. The bot must be pure Python.
6. **Time Constraints:** Bots have a strict **2ms** time limit per turn per unit.
   - Avoid complex pathfinding (like A*) across the entire map every turn.
   - Cache expensive calculations in `self`.
   - Use simple heuristics and state machines to ensure fast execution.

### Python Style & Typing

- **Python Version:** Target Python 3.12+. Utilize modern typing features (`|` for unions, `list[int]`, etc.).
- **Naming Conventions:**
  - Classes: `PascalCase` (e.g., `BuilderBot`, `Harvester`).
  - Functions & Variables: `snake_case` (e.g., `get_enemy_core`, `reserve_buffer`).
  - Constants: `UPPER_SNAKE_CASE` (e.g., `DRAIN_WAVE_DURATION`, `MAX_TURNS`).
- **Imports Structure:** Group imports logically with blank lines between groups:
  ```python
  import sys
  from collections import deque

  from cambc import Controller, Direction, EntityType, Position

  from core import Core
  from builder_bot import BuilderBot
  ```
- **Type Hinting:** Extensively use type hints. The `Controller` API must be typed to enable autocomplete and clarity.
  ```python
  class Player:
      def __init__(self) -> None:
          self.active_role: Core | BuilderBot | None = None

      def run(self, ct: Controller) -> None:
          pass
  ```

### State Management & Error Handling

- **Check Before Action:** The engine will raise exceptions or ignore commands if you attempt invalid actions (e.g., moving into a wall, spawning without resources). ALWAYS check capability first:
  ```python
  if ct.get_action_cooldown() == 0 and ct.can_spawn(target_pos):
      ct.spawn_builder(target_pos)
  ```
- **Cooldown Tracking:** Movement and actions have separate cooldowns. Verify them before issuing commands:
  - `if ct.get_action_cooldown() == 0:`
  - `if ct.get_movement_cooldown() == 0:`
- **Exception Prevention over `try/except`:** Do not rely on `try/except` to handle engine rule violations. Use the `can_...` API methods instead to avoid performance overhead.

### Debugging & Logging

Debugging must be done carefully to differentiate between local stdout and visualizer output.
- **Replay Logs (Per-Unit):** `print("Spawning unit...")`
  Standard `print()` is captured directly into the `.replay26` file and can be viewed per-unit inside the visualiser.
- **Real-Time Console Logs:** `print("Fatal state!", file=sys.stderr)`
  Prints sent to `sys.stderr` appear in the terminal in real-time during local matches.
- **Visual Overlays:** Use visual debugging directly on the game map:
  - `ct.draw_indicator_line(pos_a, pos_b, r, g, b)`
  - `ct.draw_indicator_dot(pos, r, g, b)`

---

## 3. Project Structure & Organization

Maintain the standard scaffolding provided by `cambc starter`:
- `cambc.toml`: Project configuration. Defines `bots_dir` and `maps_dir`.
- `bots/`: The directory where all bot logic resides. Each bot is a subfolder.
- `maps/`: Contains `.map26` files for custom map testing.

If you create a new bot, place it in `bots/<new_bot_name>/` and ensure it has a `main.py`.

## 4. Cursor / Copilot Integration
*(No pre-existing `.cursorrules` or `.github/copilot-instructions.md` were found in this repository. Ensure any generated code adheres strictly to the guidelines above, especially regarding the lack of file I/O during execution.)*