# Product Safety DB

Better search UX for [EU Safety Gate](https://ec.europa.eu/safety-gate-alerts/screen/search) product safety alerts.

## Prerequisites

- [Nix](https://nixos.org/) with flakes enabled

## Quick start

```bash
nix develop
just migrate
just dev        # http://localhost:8000
```

## Key commands

| Command | Description |
|---------|-------------|
| `just dev` | Start dev server at localhost:8000 |
| `just scrape` | Fetch latest TOYS alerts from Safety Gate API |
| `just test` | Run tests |
| `just lint` | Lint and format |
| `just ci` | Full CI pipeline (lint + typecheck + test) |
| `just --list` | Show all available commands |
