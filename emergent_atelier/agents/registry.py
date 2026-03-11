"""Agent registry — maps algorithm name → class.

To add a new agent type: implement BaseAgent and register it here.
"""

from __future__ import annotations

from typing import Type

from emergent_atelier.agents.base import BaseAgent
from emergent_atelier.agents.noise import NoiseAgent
from emergent_atelier.agents.edge_tracer import EdgeTracerAgent
from emergent_atelier.agents.erosion import ErosionAgent
from emergent_atelier.config.loader import AgentConfig


_REGISTRY: dict[str, Type[BaseAgent]] = {
    "noise": NoiseAgent,
    "edge_tracer": EdgeTracerAgent,
    "erosion": ErosionAgent,
}


def create_agent(config: AgentConfig) -> BaseAgent:
    """Instantiate an agent from its config."""
    cls = _REGISTRY.get(config.algorithm)
    if cls is None:
        raise ValueError(
            f"Unknown algorithm '{config.algorithm}'. "
            f"Available: {sorted(_REGISTRY.keys())}"
        )
    return cls(config)


def register_agent_class(algorithm: str, cls: Type[BaseAgent]) -> None:
    """Register a custom agent class at runtime."""
    _REGISTRY[algorithm] = cls
