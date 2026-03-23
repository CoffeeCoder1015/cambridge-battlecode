"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.

This bot:
  - Core: spawns up to 3 builder bots on random adjacent tiles, places a marker
  - Builder bot: builds a harvester on any adjacent ore tile, then moves in a
    random direction (laying a road first so the tile is passable)
"""


from cambc import Controller, EntityType

from builderbot import BuilderBot
from core import Core

mapping = {
    EntityType.CORE: Core,
    EntityType.BUILDER_BOT: BuilderBot,
}

class Player:
    def __init__(self):
        self.active:Core | BuilderBot = None

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if self.active is None:
            self.active = mapping[etype]()
        self.active.run(ct)