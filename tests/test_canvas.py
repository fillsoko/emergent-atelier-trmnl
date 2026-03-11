"""Tests for canvas state store and coordinator."""

import asyncio
import time

import numpy as np
import pytest
from PIL import Image

from emergent_atelier.canvas.coordinator import Coordinator, StagingBuffer
from emergent_atelier.canvas.state import CanvasStateStore, CANVAS_WIDTH, CANVAS_HEIGHT


@pytest.fixture
def tmp_store(tmp_path):
    return CanvasStateStore(data_dir=str(tmp_path / "canvas"), history_depth=5)


def test_initial_canvas_is_blank(tmp_store):
    v = tmp_store.current()
    assert v.cycle == 0
    arr = np.array(v.image)
    assert arr.sum() == 0  # all black


def test_commit_increments_cycle(tmp_store):
    img = Image.new("1", (CANVAS_WIDTH, CANVAS_HEIGHT), 1)
    v = tmp_store.commit(img, ["test-agent"])
    assert v.cycle == 1
    assert v.contributing_agents == ["test-agent"]


def test_history_depth_respected(tmp_store):
    for i in range(10):
        img = Image.new("1", (CANVAS_WIDTH, CANVAS_HEIGHT), i % 2)
        tmp_store.commit(img, [f"agent-{i}"])
    # depth=5 means at most 5+1 (including initial) but after trimming: 5
    assert len(tmp_store.history()) <= 5


def test_delta_pct_all_flipped(tmp_store):
    img = Image.new("1", (CANVAS_WIDTH, CANVAS_HEIGHT), 1)  # all white
    v = tmp_store.commit(img, [])
    assert v.delta_pct == 100.0


def test_delta_pct_no_change(tmp_store):
    img = Image.new("1", (CANVAS_WIDTH, CANVAS_HEIGHT), 0)  # still all black
    v = tmp_store.commit(img, [])
    assert v.delta_pct == 0.0


def test_staging_buffer_apply():
    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
    buf = StagingBuffer()
    mask = np.zeros_like(canvas)
    mask[100, 100] = True
    values = np.ones_like(canvas)
    buf.write_pixels(mask, values)
    result = buf.apply_to(canvas)
    assert result[100, 100] == True
    assert result[0, 0] == False


def test_staging_buffer_reset():
    buf = StagingBuffer()
    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
    mask = np.ones((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
    values = np.ones((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
    buf.write_pixels(mask, values)
    buf.reset()
    result = buf.apply_to(canvas)
    assert result.sum() == 0


@pytest.mark.asyncio
async def test_coordinator_cycle(tmp_path):
    store = CanvasStateStore(data_dir=str(tmp_path / "canvas"))
    coordinator = Coordinator(store)

    from emergent_atelier.config.loader import AgentConfig
    from emergent_atelier.agents.noise import NoiseAgent

    cfg = AgentConfig(name="test-noise", role="test", algorithm="noise",
                      pixel_budget=100, influence_radius=50, random_seed=0)
    coordinator.register_agent(NoiseAgent(cfg))

    initial_cycle = store.current_cycle()
    await coordinator.run_cycle()
    assert store.current_cycle() == initial_cycle + 1


def test_to_png_bytes(tmp_store):
    v = tmp_store.current()
    data = v.to_png_bytes()
    assert data[:4] == b'\x89PNG'


def test_to_png_bytes_dither(tmp_store):
    v = tmp_store.current()
    data = v.to_png_bytes(dither=True)
    assert data[:4] == b'\x89PNG'
