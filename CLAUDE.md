# Line Network — Geo Dashboard Suite

## Projects
| Dir | Status | What it is |
|-----|--------|------------|
| `snowline/` | Active | Daily snow cover map from satellite imagery |
| `riverline/` | Active | Montana river conditions dashboard |
| `skyline/` | Planned | Weather layer (Synoptic API, not started) |
| `dataline/` | Support | Shared data utilities |

## Workflow rules
- Every project keeps a `PLAN.md` in its dir + this root `PLAN.md` is an index
- Update `PLAN.md` end-of-session (saves re-reading next time)
- Default: `src/` modules with `__main__` smoke tests — notebooks only for first poke at an unfamiliar API
- Never background-run pipelines or data downloads — hand off to user

## Deployment
All sites: Cloudflare Pages. No Docker.
