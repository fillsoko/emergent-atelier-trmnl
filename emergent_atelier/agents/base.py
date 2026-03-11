"""Base agent interface.

TR-12: All agent types implementable without modifying core code.
NFR-05: Implement BaseAgent + add config file to add a new agent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from emergent_atelier.config.loader import AgentConfig
from emergent_atelier.canvas.coordinator import StagingBuffer


class BaseAgent(ABC):
    """All agents inherit from this class.

    Agents interact with the canvas via StagingBuffer ONLY — no direct
    filesystem access to the canonical PNG (TR-02).
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._rng = np.random.default_rng(config.random_seed)

    @abstractmethod
    def generate(self, canvas: np.ndarray, buf: StagingBuffer) -> None:
        """Read canvas snapshot, write pixel diffs into buf.

        Args:
            canvas: Read-only bool numpy array (H, W). True = white pixel.
            buf:    Write-only staging buffer. Call buf.write_pixels(mask, values).
        """

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    def _random_center(self, canvas: np.ndarray) -> tuple[int, int]:
        h, w = canvas.shape
        return (
            int(self._rng.integers(0, h)),
            int(self._rng.integers(0, w)),
        )

    def _influence_mask(
        self, canvas: np.ndarray, center_y: int, center_x: int
    ) -> np.ndarray:
        """Return bool mask of pixels within influence_radius of center."""
        h, w = canvas.shape
        ys = np.arange(h)[:, None]
        xs = np.arange(w)[None, :]
        dist = np.sqrt((ys - center_y) ** 2 + (xs - center_x) ** 2)
        return dist <= self.config.influence_radius

    def _budget_mask(self, mask: np.ndarray) -> np.ndarray:
        """Subsample mask to at most pixel_budget True pixels."""
        indices = np.argwhere(mask)
        budget = self.config.pixel_budget
        if len(indices) <= budget:
            return mask
        chosen = indices[self._rng.choice(len(indices), size=budget, replace=False)]
        result = np.zeros_like(mask)
        result[chosen[:, 0], chosen[:, 1]] = True
        return result
