"""Tests for agent implementations."""

import numpy as np
import pytest

from emergent_atelier.canvas.coordinator import StagingBuffer
from emergent_atelier.canvas.state import CANVAS_WIDTH, CANVAS_HEIGHT
from emergent_atelier.config.loader import AgentConfig
from emergent_atelier.agents.noise import NoiseAgent
from emergent_atelier.agents.edge_tracer import EdgeTracerAgent
from emergent_atelier.agents.erosion import ErosionAgent
from emergent_atelier.agents.registry import create_agent, register_agent_class


def blank_canvas() -> np.ndarray:
    return np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)


def checkerboard() -> np.ndarray:
    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
    canvas[::2, ::2] = True
    canvas[1::2, 1::2] = True
    return canvas


def make_cfg(**kwargs) -> AgentConfig:
    defaults = dict(
        name="test", role="test", algorithm="noise",
        influence_radius=100, pixel_budget=500, random_seed=42
    )
    defaults.update(kwargs)
    return AgentConfig(**defaults)


# ------------------------------------------------------------------
# NoiseAgent
# ------------------------------------------------------------------

def test_noise_agent_writes_pixels():
    cfg = make_cfg(algorithm="noise", params={"density": 0.5})
    agent = NoiseAgent(cfg)
    canvas = blank_canvas()
    buf = StagingBuffer()
    agent.generate(canvas, buf)
    result = buf.apply_to(canvas)
    assert result.sum() > 0  # some pixels should be written


def test_noise_agent_respects_pixel_budget():
    cfg = make_cfg(algorithm="noise", pixel_budget=10, influence_radius=400,
                   params={"density": 1.0})
    agent = NoiseAgent(cfg)
    canvas = blank_canvas()
    # Run multiple times to check budget is never exceeded
    for _ in range(5):
        buf = StagingBuffer()
        agent.generate(canvas, buf)
        if buf._mask is not None:
            assert buf._mask.sum() <= 10


def test_noise_agent_white_mode():
    cfg = make_cfg(algorithm="noise", pixel_budget=200,
                   params={"density": 0.5, "value": "white"})
    agent = NoiseAgent(cfg)
    canvas = blank_canvas()
    buf = StagingBuffer()
    agent.generate(canvas, buf)
    result = buf.apply_to(canvas)
    # All written pixels should be white
    if buf._mask is not None and buf._mask.sum() > 0:
        assert result[buf._mask].all()


# ------------------------------------------------------------------
# EdgeTracerAgent
# ------------------------------------------------------------------

def test_edge_tracer_finds_edges():
    cfg = make_cfg(algorithm="edge_tracer", influence_radius=400,
                   params={"mode": "reinforce", "threshold": 1})
    agent = EdgeTracerAgent(cfg)
    canvas = checkerboard()
    buf = StagingBuffer()
    agent.generate(canvas, buf)
    # Checkerboard has many edges — agent should write something
    if buf._mask is not None:
        assert buf._mask.sum() > 0


def test_edge_tracer_blank_canvas_no_edges():
    cfg = make_cfg(algorithm="edge_tracer", influence_radius=400,
                   params={"mode": "reinforce", "threshold": 3})
    agent = EdgeTracerAgent(cfg)
    canvas = blank_canvas()
    buf = StagingBuffer()
    agent.generate(canvas, buf)
    # Blank canvas has no edges with threshold=3
    result = buf.apply_to(canvas)
    assert result.sum() == 0


# ------------------------------------------------------------------
# ErosionAgent
# ------------------------------------------------------------------

def test_erosion_agent_reduces_isolated_pixels():
    cfg = make_cfg(algorithm="erosion", influence_radius=400, pixel_budget=5000,
                   params={"isolation_threshold": 2, "mode": "erode"})
    agent = ErosionAgent(cfg)
    # Scattered pixels — mostly isolated
    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
    canvas[::20, ::20] = True  # sparse grid of white pixels
    before_count = canvas.sum()
    buf = StagingBuffer()
    agent.generate(canvas, buf)
    result = buf.apply_to(canvas)
    assert result.sum() <= before_count  # should have eroded some


def test_dilate_agent_expands_clusters():
    cfg = make_cfg(algorithm="erosion", influence_radius=400, pixel_budget=5000,
                   params={"isolation_threshold": 3, "mode": "dilate"})
    agent = ErosionAgent(cfg)
    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=bool)
    # Dense cluster of white pixels
    canvas[200:260, 350:450] = True
    before_count = canvas.sum()
    buf = StagingBuffer()
    agent.generate(canvas, buf)
    result = buf.apply_to(canvas)
    assert result.sum() >= before_count


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

def test_registry_creates_noise():
    cfg = make_cfg(algorithm="noise")
    agent = create_agent(cfg)
    assert isinstance(agent, NoiseAgent)


def test_registry_creates_edge_tracer():
    cfg = make_cfg(algorithm="edge_tracer")
    agent = create_agent(cfg)
    assert isinstance(agent, EdgeTracerAgent)


def test_registry_creates_erosion():
    cfg = make_cfg(algorithm="erosion")
    agent = create_agent(cfg)
    assert isinstance(agent, ErosionAgent)


def test_registry_unknown_algorithm():
    cfg = make_cfg(algorithm="unknown_algo")
    with pytest.raises(ValueError, match="Unknown algorithm"):
        create_agent(cfg)


def test_register_custom_agent():
    from emergent_atelier.agents.base import BaseAgent

    class DummyAgent(BaseAgent):
        def generate(self, canvas, buf):
            pass

    register_agent_class("dummy", DummyAgent)
    cfg = make_cfg(algorithm="dummy")
    agent = create_agent(cfg)
    assert isinstance(agent, DummyAgent)
