---
id: LRN-384
title: Breaking CHANGELOG bullet and fail-loud guard need a ruling
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The GH-178 Breaking bullet said removing `_Wire._rejects_non_finite` now raises TypeError at class definition. It cited no issuecomment URL; issue 178 has no maintainer comment. The AC only asked to remove or keep the hook, so the boot-time TypeError guard was never approved.

## Root cause
A todo with no Ruling line was assumed to need no approval, and a guard beyond the AC was added.

## Check
For each Breaking bullet in CHANGELOG.md [Unreleased], confirm an `issues/NNN#issuecomment-` URL. Run `gh api repos/wailuen/a2a-sdk/issues/178/comments`.

## Prevention
When planning, require a cited issuecomment for every Breaking bullet; get separate approval for any fail-loud guard beyond the AC, or keep removal a silent no-op.
