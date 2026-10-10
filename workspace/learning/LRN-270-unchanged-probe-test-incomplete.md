---
id: LRN-270
title: Unchanged-behavior test skips listed probes
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
test_idp_on_discovery_documents_unchanged was meant to prove the OAuth-chain probes (PRM, AS metadata, 401 + WWW-Authenticate, CORS preflight) are identical with IdP on and off. It sent no 401 probe or preflight, never compared on vs off, asserted PRM against values taken from PRM itself, and checked a host (login.example.com) the fake IdP never uses.

## Root cause
The test was written as a self-referential sanity check instead of a side-by-side comparison of every probe the AC names.

## Check
In tests/test_gh152_idp_authorize_flow.py, confirm one IdP-off and one IdP-on app are built and each listed probe's bytes/status/headers are asserted equal; grep for "login.example.com" and confirm no match.

## Prevention
When an AC lists probes that must stay unchanged across a switch, plan the test to run every listed probe on both sides and compare the captures.
