"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.

This bot:
  - Core: spawns up to 3 builder bots on random adjacent tiles, places a marker
  - Builder bot: builds a harvester on any adjacent ore tile, then moves in a
    random direction (laying a road first so the tile is passable)
"""


import os
import time
if os.getenv("PROFILE"):
    import cProfile

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
        self.profiler = None
        self.te = 0

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if self.active is None:
            self.active = mapping[etype]()
        if os.getenv("PROFILE"):
            if ct.get_entity_type() == EntityType.BUILDER_BOT:
                if not self.profiler:
                    self.profiler = cProfile.Profile()
                self.profiler.enable()  # just run it the whole time
        start = time.time_ns()
        self.active.run(ct)
        end = time.time_ns()
        self.te = max(self.te,end-start)
        print(self.te)
        if os.getenv("PROFILE"):
            if ct.get_entity_type() == EntityType.BUILDER_BOT:
                self.profiler.disable()
                if ct.get_current_round() == 100:  # dump at round 500 and stop
                    self.profiler.dump_stats("profile.prof")