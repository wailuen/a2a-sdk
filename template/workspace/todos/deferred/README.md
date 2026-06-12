# Todos — deferred

Files written here when a wave or group could not complete within its round budget,
or when a protocol audit found critical findings that could not be fixed in one round.

## Filename convention

| Trigger | Filename |
|---------|----------|
| Unit group round budget exhausted (5 rounds) | `w[NNN]-group-[label]-budget-exhausted.md` |
| Wave protocol audit blocked | `w[NNN]-protocol-blocked.md` |

## File content (minimum)

```markdown
# Deferred — w[NNN] [reason]

- **Wave:** w[NNN]
- **Date:** YYYY-MM-DD
- **Reason:** budget-exhausted | protocol-blocked
- **Rounds:** N

## Unresolved findings
<list>

## Next step
Fix remaining findings, then run /agent-verify, then re-run `/wave w[NNN]`.
```

A deferred file is NOT a cancelled wave — fix the findings and re-run.
