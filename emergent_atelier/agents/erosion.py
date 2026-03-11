"""Erosion agent.

Slowly erodes isolated white pixels, preventing canvas stagnation (FR-09).
Algorithm params (via config.params):
  - isolation_threshold: int — max number of white neighbours to consider isolated (default 2)
  - mode: "erode" | "dilate" (default "erode")
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import generic_filter

from emergent_atelier.agents.base import BaseAgent
from emergent_atelier.canvas.coordinator import StagingBuffer
from emergent_atelier.config.loader import AgentConfig


def _white_neighbour_count(values: np.ndarray) -> float:
    center_idx = len(values) // 2
    neighbours = np.delete(values, center_idx)
    return float(neighbours.sum())


class ErosionAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._isolation_threshold: int = int(config.params.get("isolation_threshold", 2))
        self._mode: str = config.params.get("mode", "erode")

    def generate(self, canvas: np.ndarray, buf: StagingBuffer) -> None:
        white = canvas.astype(float)
        neighbour_counts = generic_filter(white, _white_neighbour_count, size=3)

        if self._mode == "erode":
            # Erode: white pixels with few white neighbours → flip to black
            isolated_white = canvas & (neighbour_counts <= self._isolation_threshold)
            mask = isolated_white
            values = np.zeros(canvas.shape, dtype=bool)
        else:
            # Dilate: black pixels with many white neighbours → flip to white
            isolated_black = (~canvas) & (neighbour_counts >= (8 - self._isolation_threshold))
            mask = isolated_black
            values = np.ones(canvas.shape, dtype=bool)

        cy, cx = self._random_center(canvas)
        influence = self._influence_mask(canvas, cy, cx)
        mask = mask & influence
        mask = self._budget_mask(mask)

        if mask.sum() == 0:
            return

        buf.write_pixels(mask, values)
