# w060 — group G3 — tests RED (round 1)

- Wave: w060
- Scope: unit:G3
- Date: 2026-10-23
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings unresolved.

## Blocking findings

### RT-001 (high) [SDK] — sdkCandidate: true
- File: `tests/test_gh152_idp_off_regression.py:23`
- Quote: `"/.well-known/oauth-authorization-server": "a60d7febb298579e452af65fc87852d1d91cd0c6f018ba88ae26a0012af0c4d8",`
- Description: GH-222 re-captured the authorization-server metadata golden hash in this test, but the file is not listed in the G3 todo's Creates: (or anywhere in workspace/todos/active/w060-gh-issues.md). Fails LRN-441 (high): a test changed to fit a wire change must be declared in the todo.
- Fix: Add `tests/test_gh152_idp_off_regression.py` (GOLDEN_METADATA authorization-server hash re-captured for the token_endpoint_auth_methods_supported change) to the GH-222 Creates: line in workspace/todos/active/w060-gh-issues.md, and name it in the GH-222 CHANGELOG entry's Tests list.
- Codify: When a wire change makes you re-capture a golden hash in an existing test, list that test file in the todo's Creates: in the same change.

## Instruction

Fix failing tests and remaining findings, then re-run /wave w060

## Shared working tree rule

Other agents have uncommitted work in this tree. NEVER run `git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or `git checkout .`. Edit files in place. Use `git show` / `git diff` to inspect old content.
