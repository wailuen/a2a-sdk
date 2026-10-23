---
id: LRN-436
title: Breaking CHANGELOG bullet cites no spec clause or ruling URL
category: protocol
severity: high
source: redteam
date: 2026-10-22
---

## What happened
The GH-221 bullet under Breaking changes said only "for spec conformance". It had no MCP spec clause and no issuecomment ruling URL (issue 221 had zero comments). It also sat under a heading the todo AC did not name.

## Root cause
Writers treated "spec conformance" as its own authority. LRN-357 and LRN-384 were not applied at CHANGELOG time.

## Check
For each bullet under Breaking in `[Unreleased]`, confirm it contains an exact spec clause (section name) or an `issues/<n>#issuecomment-` URL. Confirm the heading matches the todo AC.

## Prevention
When planning a wire-behaviour change, put the exact spec clauses (tool errors, Transports sections) or an owner ruling comment URL in the todo, plus the DESIGN exemption or bump basis. Do not close the wave without them.
