# Line Network

Notes for AI coding sessions in this repository. People: start with
[README.md](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md). The data
contract and measured facts are in [AGENTS.md](AGENTS.md).

## Projects
| Dir | Status | What it is |
|-----|--------|------------|
| `snowline/` | Live | Daily snow cover map from satellite imagery |
| `riverline/` | In progress | Montana river conditions dashboard |
| `skyline/` | Notes only | Weather layer, no code yet |

## Workflow rules
- Read the product's `PLAN.md` first (`snowline/PLAN.md`); the root `PLAN.md` is an index.
  Update the plan when the state it describes changes.
- `main` deploys to the live site on every push, and CI bots commit data to `main`
  several times a day. Work on a branch and rebase before pushing.
- Never hand-edit or commit regenerated data files (`snowline/site/data/`,
  `snowline/site/data_10m/`, `snowline/site/stac/`). CI owns them.
- New Python goes in `lib/` or `<product>/pipeline/` with a `__main__` smoke test.
- Don't start long pipeline runs or downloads in the background on a laptop
  session. Hand the command to the person, or let GitHub Actions run it.

## Deployment
Cloudflare Pages from `main`, repository root, with `_worker.js`. No Docker.
