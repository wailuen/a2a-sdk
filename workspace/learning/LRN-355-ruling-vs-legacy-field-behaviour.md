---
id: LRN-355
title: Wave kept legacy behaviour that conflicts with new maintainer ruling
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The GH-173 ruling says every nullable numeric content field coerces non-finite to None. `BriefingKpiItem.delta` (`float | None`) still rejected nan/inf via the GH-95 validator and `_rejects_non_finite = True`. The wave only noted this in the CHANGELOG.

## Root cause
The wave treated a CHANGELOG note as an exemption; no recorded maintainer exception existed.

## Check
Run `BriefingKpiItem(title='t', value=1.0, delta=float('nan')).delta is None`. grep `_rejects_non_finite` in agent_sdk/models/content_types.py; any hit on a nullable field must cite a maintainer issue URL.

## Prevention
When a new ruling conflicts with older field behaviour, plan to change the old behaviour (and invert its test) unless a maintainer exception URL is cited. Waves cannot self-grant exceptions.
