---
name: changelog
category: core
description: "Generate a human-readable, categorised changelog for agent-sdk between two commit SHAs. Called by /upgrade; also useful standalone when evaluating whether to upgrade."
---

# /changelog — SDK changelog between versions

Produce a categorised changelog from the SDK git history between two SHAs.
Highlights breaking changes, protocol surface changes, and security patches.

## Usage

```
/changelog <from-sha> <to-sha> [<sdk-git-url>]
```

- `from-sha` — the SHA currently pinned in `pyproject.toml`
- `to-sha` — the SHA being considered (or `HEAD` of the remote)
- `sdk-git-url` — scheme-less git URL (defaults to the value in `pyproject.toml`)

Called automatically by `/upgrade` step 4. Can be run standalone to evaluate
a prospective upgrade before committing to it.

## Steps

1. **Resolve the SDK path.**
   Check if the SDK repo is available locally (a sibling of the agent repo, or at
   a path the user provides). If available: use `git log` directly.
   If not: `git clone --filter=blob:none --no-checkout <url> /tmp/sdk-changelog-clone`
   (blobless, shallow-ish — fast). Clean up the clone when done.

2. **Fetch the commit range.**
   `git log <from-sha>..<to-sha> --pretty=format:"%H %s" --reverse`
   This gives every commit between the current pin and the target, oldest-first.

3. **Categorise each commit** by scanning the subject line for conventional-commit
   prefixes and SDK-specific keywords:

   | Category | Triggers | Display label |
   |----------|----------|---------------|
   | Breaking | `BREAKING`, `!:`, `feat!`, `fix!` in subject | 🔴 BREAKING |
   | Protocol | `a2a`, `mcp`, `ag-ui`, `a2ui`, `oauth` (case-insensitive) in subject | 🟡 Protocol |
   | Security | `SI-`, `credential`, `auth`, `CVE` in subject | 🟠 Security |
   | Feature | `feat:` prefix | ✅ Feature |
   | Fix | `fix:` prefix | 🔧 Fix |
   | Test / CI | `test:`, `ci:` prefix | 🧪 Test/CI |
   | Other | anything else | — Other |

4. **Read the body** of any BREAKING or Protocol commit (`git show <sha>`) to surface
   the migration note if present.

5. **Produce the changelog** in this format:

```
## agent-sdk changelog: <from-sha7> → <to-sha7>
<N> commits

### 🔴 Breaking changes
- <sha7> <subject>
  > <migration note if present>

### 🟡 Protocol surface changes
- <sha7> <subject>

### 🟠 Security patches
- <sha7> <subject>

### ✅ Features
- <sha7> <subject>

### 🔧 Fixes
- <sha7> <subject>

### — Other
- <sha7> <subject>

Omit empty sections.
```

6. **Emit a recommendation:**
   - Zero breaking or protocol changes → "Safe to upgrade — run `/upgrade` to proceed."
   - Protocol changes present → "Review protocol changes — run `/agent-verify` after upgrade."
   - Breaking changes present → "Breaking changes present — review migration notes before upgrading."

## Rules

- If `from-sha == to-sha`, emit "No changes — already at this version."
- If the range is > 200 commits, summarise (counts per category) rather than listing
  every commit — flag this to the user.
- Never fabricate commit messages. If git access fails, say so explicitly.
