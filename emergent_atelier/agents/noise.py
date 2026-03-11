"""Noise-layer agent.

Scatters random black/white pixels within its influence radius.
Algorithm params (via config.params):
  - density: float [0, 1] — fraction of influence area to fill (default 0.1)
  - value:   "random" | "white" | "black"               (default "random")
"""

from __future__ import annotations

import numpy as np

from emergent_atelier.agents.base import BaseAgent
from emergent_atelier.canvas.coordinator import StagingBuffer
from emergent_atelier.config.loader import AgentConfig


class NoiseAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._density: float = float(config.params.get("density", 0.1))
        self._value: str = config.params.get("value", "random")

    def generate(self, canvas: np.ndarray, buf: StagingBuffer) -> None:
        cy, cx = self._random_center(canvas)
        influence = self._influence_mask(canvas, cy, cx)

        # Apply density — randomly thin out the influence area
        density_mask = self._rng.random(canvas.shape) < self._density
        mask = influence & density_mask
        mask = self._budget_mask(mask)

        if mask.sum() == 0:
            return

        if self._value == "white":
            values = np.ones(canvas.shape, dtype=bool)
        elif self._value == "black":
            values = np.zeros(canvas.shape, dtype=bool)
        else:
            values = self._rng.integers(0, 2, size=canvas.shape).astype(bool)

        buf.write_pixels(mask, values)
