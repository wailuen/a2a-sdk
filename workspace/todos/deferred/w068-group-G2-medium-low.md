# w068 — unit:G2 — deferred medium/low findings

- Wave: w068
- Scope: unit:G2
- Date: 2026-10-25

Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — tests/test_gh269_agui_text_scrub.py:75
Quote: `    assert "more" in _text(node)`
- Description: test_fallback_clips_prose_before_splitting does not detect whether the text is clipped to MAX_PROSE before splitting. The input is 1000 lines of 100 chars. With the old per-line clip plus capRows it still shows 100 lines and a '900 more' note, so the test passes either way. The AC part 'with the text clipped to MAX_PROSE first' is not pinned (LRN-544/LRN-560).
- Fix: Assert the exact count the clip-first rule gives: clip(big, MAX_PROSE) keeps 20000 chars, about 198 lines, so assert f"{n - r['max']} more" where n = len(clip(big, 20000).split('\n')) (98 more, not 900 more). Or use input whose line count only passes MAX_ROWS without the clip.
- Codify: A cap-ordering test must use input where the old order and the new order give different visible output; checking only that a 'more' note exists cannot tell them apart.
- SDK candidate: yes

## RT-002 (medium) — agent_sdk/routes/ag_ui.py:395
Quote: `                content = str(event.error) if event.error is not None else "tool failed"`
- Description: GH-269 scrubs only TEXT_MESSAGE_CONTENT.delta. Other text the AG-UI mapper writes is still not scrubbed: the tool-error TOOL_CALL_RESULT content (str(event.error)), TOOL_PROGRESS/AGENT_PROGRESS message, AGENT_NOTE note and toolCallName. A lone surrogate in any of them still ends the run with RUN_ERROR. The A2A route scrubs its whole wire (agent_sdk/routes/a2a.py:689), so the two transports behave differently on the same input.
- Fix: In _emit, serialize sse_data(scrub_unencodable(frame)) for every frame (C-040). That covers every text field in one place, including the TEXT path, and leaves the ValueError branch only for non-finite floats. Add a test with a lone surrogate in a failing tool's error text that ends with RUN_FINISHED.
- Codify: Scrub unencodable text once at the transport's frame-serialization choke point, not field by field, or new text fields will keep getting missed.
- SDK candidate: yes

## RT-003 (low) — tests/test_gh239_console_caps.py:427
Quote: `    assert max(lens) <= 20000`
- Description: The existing GH-255 fallback test was weakened by deleting the '"short" in ...' check. Nothing replaced it. The test now passes under both per-line clip and whole-text clip, so it no longer pins any ordering.
- Fix: Replace the deleted check with `and "short" not in _texts(r["nodes"][0])`. That pins the new clip-before-split rule: text past MAX_PROSE is dropped.
- SDK candidate: yes

## RT-004 (low) — agent_sdk/routes/ag_ui.py:711
Quote: `        # ValueError cut the stream with no terminal frame. Any already-`
- Description: The _emit comment block still describes the old failure branch. It does not say that a TEXT_MESSAGE_START opened earlier in the same batch is closed with a TEXT_MESSAGE_END before RUN_ERROR, or that only text-message triples are tracked (tool-call triples are not).
- Fix: Extend the comment: on failure, close any open text message with TEXT_MESSAGE_END (GH-269), then send one RUN_ERROR. Also note why TOOL_CALL_* need no tracking (the ARGS delta comes from _tool_json, which always returns encodable text).
- SDK candidate: yes

## RT-005 (low) — tests/test_gh269_agui_text_scrub.py:6
Quote: `import pytest`
- Description: Unused import: nothing in the new test file uses pytest.
- Fix: Remove the `import pytest` line.
- SDK candidate: yes

---

Autoloop cycle 4 (2026-10-26): critical/high-only filter. The 4 high candidates (sdk-candidates 2/4/5, G3 migration line) were re-verified at v0.25.0: all fixed or low. Nothing filed; loop finished.
