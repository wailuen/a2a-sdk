# LRN-052 — gitignored/untracked path cannot land in a wave todo

| Field      | Value                                          |
|------------|------------------------------------------------|
| Category   | planning                                       |
| Severity   | high                                           |
| Source     | redteam (RT-001, w020)                         |
| Date       | 2026-06-18                                     |
| Wave       | w020                                           |
| GH issue   | GH-70d                                         |

## Finding

`GH-70d` planned a `Modifies: template/Dockerfile` change inside this repo. `template/` is listed in `.gitignore` at line 38 and has zero git-tracked files (`git ls-files template/` → empty; commit e7bf0a1 stopped tracking it). The canonical `Dockerfile` lives in the separate `wailuen/agent-template` repo. The change can never be committed or propagated from `a2a-sdk`, making the todo silently undeliverable.

## Pattern

**Gitignored-path wave todo** — a Creates:/Modifies: path in a todo resolves to a tree that is gitignored or fully untracked in the current repo. The todo appears planned but cannot land.

## Root cause

The planner did not verify that every `Modifies:`/`Creates:` path in a todo is git-tracked before adding it to the wave plan. Gitignore status and multi-repo splits are not checked at planning time.

## Prevention

Before finalising any wave plan, run `git ls-files <path>` for every `Modifies:`/`Creates:` path in each todo. If the output is empty, the path is not in this repo and the todo must be:

1. Re-scoped to the correct repo (open a PR there), OR
2. Marked `[~]` (out-of-repo) in the wave plan with the target repo noted.

Never mark an out-of-repo todo `[x]` (done) from the current wave.

## Checklist for wave planners

- [ ] For every `Modifies:`/`Creates:` path: `git ls-files <path>` must return at least one line.
- [ ] If `git ls-files` returns empty: check `.gitignore` and the repo split; re-file or mark `[~]`.
- [ ] Record the correct target repo in the todo entry so the fix is not lost.
- [ ] Do not close the upstream GH issue until the change lands in the correct repo.
