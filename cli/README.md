# VibeShorts CLI

Command-line interface only. Shared agents, models, Vertex/MCP clients, and the render pipeline live in `src/vibeshorts/` at the repo root.

```
VibeShorts/               # git repo (this product)
├── src/vibeshorts/       # shared engine (Python package)
├── cli/                  # this folder
└── webui/                # future Web UI
```

Entry point: `vibeshorts` → `vibeshorts.cli.main:app`

```bash
pip install -e ".[preprocess]"
vibeshorts --help
```

Commands: `init`, `create`, `render`, `studio`, `chat`, `config`.

Full product docs: [../README.md](../README.md)
