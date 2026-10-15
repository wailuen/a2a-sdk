---
id: LRN-391
title: SI-5 listed surfaces left without tests
category: testing
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The SI-5 annotation (LRN-224) listed identity-decision surfaces. Consent approval (routes/oauth.py:912) and the task identity-binding bypass (tasks/memory.py:185) had no test for service keys. The code is correct only because `service` is separate from `admin`; a later `admin or service` change would pass the suite.

## Root cause
Surfaces whose code did not need to change were treated as done, so nothing pinned their behavior.

## Check
In tests/test_gh182_service_key.py, confirm `test_service_key_refused_on_oauth_consent` (Bearer and `api_key` form field) and `test_service_key_cannot_read_other_identity_task` (404, no existence leak) exist and pass.

## Prevention
An SI-5 annotation that lists surfaces is closed only when each surface has its own test, even if the code there did not change. Planner: one AC and one test per listed surface.
