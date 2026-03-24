import random

from cambc import Controller

from ..Movement.TangentBug import TangentBug
from ..helpers import execute_nav_step, set_nav_target


class GaurdedConveryMove:
    def __init__(self) -> None:
        self.nav = TangentBug()
        self._target_set = False
        self._last_nav_target: tuple[int, int] | None = None

    def _choose_exploration_target(self, ct: Controller) -> tuple[int, int]:
        width = ct.get_map_width()
        height = ct.get_map_height()
        return (random.randrange(width), random.randrange(height))

    def run(self, ct: Controller) -> bool:
        if not self._target_set:
            tx, ty = self._choose_exploration_target(ct)
            self._last_nav_target, self._target_set = set_nav_target(
                nav=self.nav,
                last_nav_target=self._last_nav_target,
                tx=tx,
                ty=ty,
            )

        acted = execute_nav_step(ct, self.nav)
        if acted:
            return True

        # If we can't progress on current target, retarget and try once.
        tx, ty = self._choose_exploration_target(ct)
        self._last_nav_target, self._target_set = set_nav_target(
            nav=self.nav,
            last_nav_target=self._last_nav_target,
            tx=tx,
            ty=ty,
        )
        return execute_nav_step(ct, self.nav)
