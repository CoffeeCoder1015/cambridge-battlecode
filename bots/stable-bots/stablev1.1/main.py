from cambc import Controller, EntityType

from builder_bot.main import BuilderBot
from core.main import Core


class Player:
    def __init__(self) -> None:
        self.active: Core | BuilderBot | None = None

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()

        if etype == EntityType.CORE:
            if self.active is None:
                self.active = Core()
            self.active.run(ct)
            return

        if etype == EntityType.BUILDER_BOT:
            if self.active is None:
                self.active = BuilderBot()
            self.active.run(ct)
