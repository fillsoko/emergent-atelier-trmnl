"""Agent configuration loader.

FR-14: Each agent defined by YAML/JSON config.
FR-15: Agents can be enabled/disabled at runtime.
NFR-05: Adding new agent type = implement interface + add config file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AgentConfig:
    name: str
    role: str
    algorithm: str                 # Maps to agent class name
    influence_radius: int = 50     # Max pixel distance agent can affect
    pixel_budget: int = 1000       # Max pixels agent may change per cycle
    scheduling_weight: float = 1.0 # Higher = applied later (wins conflicts)
    enabled: bool = True
    random_seed: int | None = None
    params: dict[str, Any] = field(default_factory=dict)  # Algorithm-specific knobs


def load_agent_config(path: str | Path) -> AgentConfig:
    p = Path(path)
    raw: dict[str, Any]
    if p.suffix in (".yaml", ".yml"):
        with p.open() as f:
            raw = yaml.safe_load(f)
    elif p.suffix == ".json":
        with p.open() as f:
            raw = json.load(f)
    else:
        raise ValueError(f"Unsupported config format: {p.suffix}")

    return AgentConfig(
        name=raw["name"],
        role=raw["role"],
        algorithm=raw["algorithm"],
        influence_radius=int(raw.get("influence_radius", 50)),
        pixel_budget=int(raw.get("pixel_budget", 1000)),
        scheduling_weight=float(raw.get("scheduling_weight", 1.0)),
        enabled=bool(raw.get("enabled", True)),
        random_seed=raw.get("random_seed"),
        params=raw.get("params", {}),
    )


def load_all_configs(config_dir: str | Path) -> list[AgentConfig]:
    d = Path(config_dir)
    configs = []
    for p in sorted(d.glob("*.yaml")) + sorted(d.glob("*.json")):
        try:
            configs.append(load_agent_config(p))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to load config %s: %s", p, exc)
    return configs
