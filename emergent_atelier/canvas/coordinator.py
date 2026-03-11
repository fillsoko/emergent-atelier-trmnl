"""Canvas coordinator — merges agent staging buffers in deterministic order.

FR-03: Coordinator merges contributions in priority/timestamp order.
FR-04: Agents have configurable influence radius.
TR-03: Coordinator is the single writer to the canonical PNG.
NFR-03: Cycle must complete in ≤ 30s for 5 agents.
NFR-04: Deterministic given same seed, configs, random seed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from emergent_atelier.canvas.state import CanvasStateStore, CANVAS_WIDTH, CANVAS_HEIGHT

if TYPE_CHECKING:
    from emergent_atelier.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class StagingBuffer:
    """Per-agent staging buffer. Holds pixel diffs."""

    def __init__(self) -> None:
        # None means "no contribution"; bool array means explicit pixel values
        self._data: np.ndarray | None = None
        self._mask: np.ndarray | None = None  # True where agent wrote

    def write_pixels(self, mask: np.ndarray, values: np.ndarray) -> None:
        """Record pixel diffs. mask is bool array (H,W); values is bool array (H,W)."""
        if self._data is None:
            self._data = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
            self._mask = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
        self._mask |= mask
        self._data[mask] = values[mask]

    def apply_to(self, canvas: np.ndarray) -> np.ndarray:
        """Merge this buffer into canvas array. Returns new canvas."""
        if self._data is None or self._mask is None:
            return canvas
        result = canvas.copy()
        result[self._mask] = self._data[self._mask]
        return result

    def reset(self) -> None:
        self._data = None
        self._mask = None


class Coordinator:
    """Runs a canvas evolution cycle.

    1. Provides each registered agent with a read-only canvas snapshot and a StagingBuffer.
    2. Runs agents concurrently (asyncio).
    3. Merges staging buffers in agent priority order (lowest priority value = first applied,
       so higher-priority agents overwrite lower-priority ones).
    4. Commits merged result to CanvasStateStore.
    """

    def __init__(self, store: CanvasStateStore) -> None:
        self._store = store
        self._agents: list[BaseAgent] = []

    def register_agent(self, agent: BaseAgent) -> None:
        self._agents.append(agent)
        self._agents.sort(key=lambda a: a.config.scheduling_weight, reverse=True)

    def registered_agents(self) -> list[BaseAgent]:
        return list(self._agents)

    async def run_cycle(self) -> None:
        """Execute one full evolution cycle."""
        t0 = time.monotonic()
        active = [a for a in self._agents if a.config.enabled]
        if not active:
            logger.warning("No active agents — skipping cycle.")
            return

        # Snapshot current canvas
        current_version = self._store.current()
        canvas_snapshot = np.array(current_version.image, dtype=bool)

        # Create staging buffers
        buffers: dict[str, StagingBuffer] = {a.config.name: StagingBuffer() for a in active}

        # Run agents concurrently
        tasks = [
            asyncio.create_task(
                self._run_agent(a, canvas_snapshot.copy(), buffers[a.config.name])
            )
            for a in active
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Merge in priority order (high scheduling_weight applied last = wins)
        sorted_agents = sorted(active, key=lambda a: a.config.scheduling_weight)
        merged = canvas_snapshot.copy()
        for agent in sorted_agents:
            merged = buffers[agent.config.name].apply_to(merged)

        new_image = Image.fromarray(merged.astype(np.uint8) * 255, mode="L").convert("1")
        version = self._store.commit(new_image, [a.config.name for a in active])

        elapsed = time.monotonic() - t0
        logger.info(
            "Cycle %d complete in %.2fs — agents=%s delta=%.2f%%",
            version.cycle,
            elapsed,
            [a.config.name for a in active],
            version.delta_pct,
        )

    @staticmethod
    async def _run_agent(agent: BaseAgent, canvas: np.ndarray, buf: StagingBuffer) -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, agent.generate, canvas, buf)
        except Exception:
            logger.exception("Agent %s failed during generation", agent.config.name)
