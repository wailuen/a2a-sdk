---
id: LRN-461
title: Public-output redaction tested only on AC sample secrets
category: security
severity: high
source: redteam
date: 2026-10-23
---

## What happened
The auto-filer redaction in harness/workflows/wave-cycle.js (FILE_SDK_ISSUES_PY, LONG regex `{40,}`) passed AWS keys with `/`, 39-char Google keys, Basic auth, JWT headers, glpat-, pk_live_, `password=` and xoxb- unredacted. leaks() also returned False, so they could reach a public GitHub issue.

## Root cause
Patterns and tests covered only the `sk-`/`ak_` samples named in the AC; the base64 class omitted `/` and `.` and the length floor was too high.

## Check
Verify tests/test_wave_cycle_behaviour.py::test_filer_never_puts_secrets_in_gh_argv_or_body is parametrized with AWS, AIza, JWT `eyJ`, `Basic `, glpat-, pk_live_, `password=`, xoxb- samples; grep `AIza` and `glpat` in FILE_SDK_ISSUES_PY.

## Prevention
When planning any filter that writes to public output, require a test matrix of real secret formats (AWS, Google, JWT, Basic, GitLab, Stripe, Slack), used in both redact and leaks(), not only AC samples.
