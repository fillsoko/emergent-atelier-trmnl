# Emergent Atelier

> Multi-agent evolving pixel art for TRMNL eInk displays.

Multiple AI agents collaborate asynchronously on a shared 800×480 canvas, each contributing pixel-level changes that accumulate into evolving generative art — served directly to your TRMNL device.

## Quickstart (Docker)

```bash
git clone https://github.com/fillsoko/TRMNL_Art.git
cd TRMNL_Art
docker compose up
```

Then open **http://localhost:8000** for the live dashboard.

Your TRMNL device polls **http://localhost:8000/image.png** every 15 minutes.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Coordinator                         │
│  Runs each agent concurrently → merges staging      │
│  buffers in priority order → commits to store       │
└────────────┬─────────────────────────┬──────────────┘
             │                         │
    ┌────────▼────────┐       ┌────────▼────────┐
    │  Canvas Store   │       │   FastAPI Server │
    │  (versioned PNG)│       │  /image.png      │
    │  10-frame hist  │       │  /  (dashboard)  │
    └─────────────────┘       └─────────────────-┘
             ▲
    ┌────────┴─────────────────────────────────────────┐
    │  Agents (each writes to StagingBuffer, not disk) │
    │  noise-layer · edge-tracer · erosion · ...       │
    └──────────────────────────────────────────────────┘
```

### Agent lifecycle (one cycle)

1. Coordinator snapshots current canvas
2. All active agents run concurrently in thread pool
3. Each agent reads snapshot, writes pixel diffs to its staging buffer
4. Coordinator merges buffers (low → high scheduling_weight)
5. Merged canvas committed to store; PNG persisted to disk

## Adding Agents

1. Implement `BaseAgent` in `emergent_atelier/agents/your_agent.py`
2. Register: `register_agent_class("your_algo", YourAgent)` in `registry.py`
3. Add a config file in `configs/`:

```yaml
name: my-agent
role: pattern-generator
algorithm: your_algo
influence_radius: 100
pixel_budget: 500
scheduling_weight: 2.0
enabled: true
params:
  my_param: value
```

## Built-in Agent Types

| Algorithm | Role | Description |
|---|---|---|
| `noise` | compositor | Scatters random pixels within influence area |
| `edge_tracer` | detail-artist | Detects and reinforces/inverts canvas edges |
| `erosion` | eroder/dilator | Erodes isolated pixels or dilates clusters |

## TRMNL Integration

1. Point your TRMNL device's plugin to `http://<your-host>:8000/image.png`
2. Set polling interval to 15 min (or match `--refresh`)
3. The plugin manifest is available at `http://localhost:8000/plugin.json`

For TRMNL X (grayscale, 1872×1404), use `http://localhost:8000/image.png?dither=true`

## Configuration

| Flag | Default | Description |
|---|---|---|
| `--config-dir` | `configs/` | Agent config directory |
| `--seed` | blank canvas | Seed image path |
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8000` | Port |
| `--refresh` | `900` | Cycle interval (seconds) |
| `--history-depth` | `10` | Versions retained |
| `--data-dir` | `data/canvas` | PNG persistence dir |

## Development

```bash
pip install -r requirements.txt
python main.py --refresh 30   # fast cycling for dev
```

Run tests:
```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## License

Apache 2.0
