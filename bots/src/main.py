"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.

This bot:
  - Core: spawns up to 3 builder bots on random adjacent tiles, places a marker
  - Builder bot: builds a harvester on any adjacent ore tile, then moves in a
    random direction (laying a road first so the tile is passable)
"""

from cambc import Controller, EntityType

from core.main import Core
from builder_bot.main import BuilderBot


class Player:
    def __init__(self):
        self.active: Core | BuilderBot | None = None

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()

        if etype == EntityType.CORE:
            if self.active is None:
                self.active = Core()
            self.active.run(ct, self)

        elif etype == EntityType.BUILDER_BOT:
            if self.active is None:
                self.active = BuilderBot()
            self.active.run(ct)
