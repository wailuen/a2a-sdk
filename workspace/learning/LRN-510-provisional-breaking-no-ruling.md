---
id: LRN-510
title: Provisional-surface break still needs ruling or move
category: protocol
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The Breaking bullet for the `preferredTransport` default (A2A v0.3.0 says absent means JSONRPC) had no `issues/245#issuecomment-` URL. GH-245 had zero comments, so it failed the LRN-444 and LRN-384 checks.

## Root cause
A spec clause was cited, but no maintainer ruling covered shipping the change as Breaking on a provisional surface.

## Check
Grep the `preferredTransport` bullet in CHANGELOG.md for `issuecomment-`. If absent, confirm the bullet sits under `### Changed` with a provisional-surface notice (as done for GH-221), not under Breaking.

## Prevention
When planning a break to a provisional surface, either obtain a ruling comment covering that exact item and cite its URL, or plan the entry under Changed with a provisional notice. Never self-ratify.
