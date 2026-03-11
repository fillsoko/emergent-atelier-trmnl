"""Edge-tracer agent.

Detects edges in the current canvas and reinforces or inverts them.
Algorithm params (via config.params):
  - mode:      "reinforce" | "invert"  (default "reinforce")
  - threshold: int 1-8 — neighbour count threshold for edge detection (default 3)
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import generic_filter

from emergent_atelier.agents.base import BaseAgent
from emergent_atelier.canvas.coordinator import StagingBuffer
from emergent_atelier.config.loader import AgentConfig


def _count_different_neighbours(values: np.ndarray) -> float:
    """Filter kernel: count neighbours with different value from center."""
    center = values[len(values) // 2]
    return float((values != center).sum())


class EdgeTracerAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._mode: str = config.params.get("mode", "reinforce")
        self._threshold: int = int(config.params.get("threshold", 3))

    def generate(self, canvas: np.ndarray, buf: StagingBuffer) -> None:
        float_canvas = canvas.astype(float)
        edge_counts = generic_filter(float_canvas, _count_different_neighbours, size=3)
        edge_mask = edge_counts >= self._threshold

        # Apply influence radius around a random center
        cy, cx = self._random_center(canvas)
        influence = self._influence_mask(canvas, cy, cx)
        mask = edge_mask & influence
        mask = self._budget_mask(mask)

        if mask.sum() == 0:
            return

        if self._mode == "invert":
            values = ~canvas
        else:
            # Reinforce: set edge pixels to white (draw the edge)
            values = np.ones(canvas.shape, dtype=bool)

        buf.write_pixels(mask, values)
