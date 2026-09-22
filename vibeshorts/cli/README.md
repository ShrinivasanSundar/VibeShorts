# VibeShorts CLI

Command-line interface only. Shared agents, models, Vertex/MCP clients, and the render pipeline live one level up in `src/vibeshorts/`.

```
vibeshorts/
├── src/vibeshorts/   # shared engine
├── cli/              # this folder
└── webui/            # future Web UI
```

Entry point: `vibeshorts` → `vibeshorts.cli.main:app`

```bash
cd vibeshorts
pip install -e ".[preprocess]"
vibeshorts --help
```

Commands: `init`, `create`, `render`, `studio`, `chat`, `config`.

Full product docs: [../README.md](../README.md)
