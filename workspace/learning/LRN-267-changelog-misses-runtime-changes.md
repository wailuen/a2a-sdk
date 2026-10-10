---
id: LRN-267
title: CHANGELOG labels runtime wave as docs-only
category: ops
severity: high
source: redteam
date: 2026-10-09
---

## What happened
The [Unreleased] CHANGELOG called the wave "GH-152-D, docs/tests only, no runtime change", yet the wave added two routes, federated GET /oauth/authorize, added Identity.user and principal_key, and new OAuthTokenStore kwargs. No GH-152-B/C/D entries or "### Added" heading existed, and a "no new unreleased work" note went stale.

## Root cause
The changelog was written from the last todo only, not reconciled against every runtime todo in the wave.

## Check
For each todo in the wave, grep CHANGELOG.md [Unreleased] for its GH-NNN id; confirm no "no runtime change" text when the diff touches agent_sdk/.

## Prevention
When planning archive for a wave, add a step: one CHANGELOG entry per runtime todo (routes, public stable-core fields, new kwargs), and update stale reconciliation sentences.
