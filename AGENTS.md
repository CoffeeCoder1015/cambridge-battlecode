# AGENTS.md - Cambridge Battlecode Bot Development Guide

This document provides guidelines for agents working on this Cambridge Battlecode bot repository.

---

## 1. Project Overview

Cambridge Battlecode is a real-time strategy game where you program bots to compete. Each unit (Core, Builder Bot, turrets) runs its own `Player` instance. The engine calls `run(controller)` once per round.

- **Language**: Python 3.12+
- **Game Engine**: `cambc` CLI and Python module (Rust-based)
- **Bot Directory**: `bots/`
- **Map Directory**: `maps/`
- **Config**: `cambc.toml`

---

## 2. Build, Run & Test Commands

### Running Local Matches

```bash
# Run a match between two bots
cambc run <bot_a> <bot_b> [map]

# Examples
cambc run starter starter
cambc run my_bot opponent --seed 42
cambc run my_bot opponent maps/custom.map26
cambc run my_bot opponent --replay out.replay26

# Auto-open visualiser after match
cambc run --watch my_bot opponent
```

### Viewing Replays

```bash
cambc watch replay.replay26
cambc watch --match <match_id>
cambc watch --match <match_id> --game 3
```

### Remote Test Runs (2ms time limit enforced)

```bash
# Authenticate first
cambc login

# Run test match
cambc test-run my_bot opponent
cambc test-run my_bot opponent maps/custom.map26
```

### Submitting Bots

```bash
cambc submit ./my_bot/    # directory (auto-zipped)
cambc submit my_bot.py    # single file
cambc submit my_bot.zip   # pre-zipped
```

### Other CLI Commands

```bash
cambc --version           # Check version
cambc status              # Show team rating and status
cambc matches             # List recent matches
cambc teams search <query>  # Search teams
```

---

## 3. Code Style Guidelines

### General Principles

- Keep code simple and readable - bots run with a strict 2ms CPU time limit
- Avoid expensive operations in the game loop
- Use local variables over repeated method calls
- Profile code if performance is a concern

### Imports

```python
# Standard library first
import random
from collections import deque

# Third-party (cambc is the main one)
from cambc import Controller, Direction, EntityType, Environment, Position

# Local imports
import core
import builder_bot
```

- Use wildcard import (`from cambc import *`) to get all game types
- Separate import groups with blank lines
- Sort imports alphabetically within groups

### Type Hints

```python
# Use type hints for function signatures
def run(ct: Controller, player) -> None:
    etype: EntityType = ct.get_entity_type()

# Simple types can be inline; complex types can be explicit
def some_function(items: list[int]) -> dict[str, int]:
```

### Naming Conventions

- **Classes**: `PascalCase` (e.g., `Player`, `BuilderBot`)
- **Functions/variables**: `snake_case` (e.g., `run`, `num_spawned`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DIRECTIONS`)
- **Files**: `snake_case.py`
- Abbreviations: Use full words (e.g., `builder_bot` not `builderbot`)

### Code Organization

```
bots/
├── starter/           # Example bot
│   └── main.py       # Contains Player class
├── src/              # Another example
│   ├── main.py
│   ├── core.py
│   └── builder_bot.py
└── q_learning/       # Q-learning bot
    ├── main.py
    ├── core.py
    └── builder_bot.py
```

Each bot needs a `main.py` with a `Player` class:

```python
from cambc import Controller, EntityType

class Player:
    def __init__(self):
        self.state = 0

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            # handle core logic
        elif etype == EntityType.BUILDER_BOT:
            # handle builder bot logic
```

### Error Handling

- Use `GameError` for game logic errors (raised by `cambc` on invalid actions)
- Always check `can_*` methods before actions:
  ```python
  if ct.can_spawn(spawn_pos):
      ct.spawn_builder(spawn_pos)
  ```
- Wrap action logic in try/except if you want graceful handling:
  ```python
  try:
      ct.move(direction)
  except GameError:
      pass  # action wasn't valid
  ```

### Formatting

- Maximum line length: 100 characters (soft guideline)
- Use 4 spaces for indentation
- One blank line between top-level definitions
- No trailing whitespace
- The project uses **ruff** for linting

### Linting

```bash
# Install ruff if needed
pip install ruff

# Run linting
ruff check bots/

# Format code
ruff format bots/
```

---

## 4. Debugging

- `print()` statements are captured to the replay
- `stderr` prints to console in real time
- Visual debug overlays:
  ```python
  c.draw_indicator_line(pos_a, pos_b, r, g, b)
  c.draw_indicator_dot(pos, r, g, b)
  ```

---

## 5. Bot Requirements

| Constraint | Limit |
|------------|-------|
| Zip size | 5 MB max |
| Decompressed size | 50 MB max |
| File count | 500 files max |
| Native extensions | Not allowed |
| CPU time | 2ms per unit per round |

- Must contain a `main.py` with a `Player` class
- Imports must be top-level (file I/O is blocked during `run()`)

---

## 6. Example Bot Structure

```python
"""Bot description here."""

import random
from cambc import *

class Player:
    def __init__(self):
        self.num_spawned = 0

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            # Core logic
            if ct.can_spawn(some_pos):
                ct.spawn_builder(some_pos)
        elif etype == EntityType.BUILDER_BOT:
            # Builder bot logic
            pass
```

---

## 7. Key Files

| File | Description |
|------|-------------|
| `cambc.toml` | Project config (bots_dir, maps_dir, replay, seed) |
| `bots/src/main.py` | Example bot entry point |
| `bots/starter/main.py` | Simple starter bot |
| `bots/q_learning/` | Q-learning implementation |
| `docs.md` | Full API reference |
| `setup.md` | Installation and CLI reference |
