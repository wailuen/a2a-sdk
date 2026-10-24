# w062 — unit:G3 — deferred medium/low findings

- Wave: w062
- Scope: unit:G3
- Date: 2026-10-23

Non-blocking — these did not block w062's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — workspace/components/README.md:116

- Description: GH-214 rewrote the C-015 section and it still says "Verified against current code", but the consumer line numbers it cites are stale: chat.js 'lines 407-408' and 'lines 669-670', and testing/chat.py 'lines 421-427'. The real sites are chat.js 457-458 and 732-733, and testing/chat.py 463-466. The AC says 'either way the registry matches the code', and it does not.
- Fix: Update the C-015 section so it names the consumer sites by symbol (handleA2aArtifact / the AG-UI CUSTOM A2UI_UPDATE handler in chat.js, extract_a2ui in testing/chat.py) or by their current line numbers. Or drop the 'Verified against current code' claim.
- Codify: When a wave edits a component registry entry that cites line numbers, it must re-check every cited line against the current file, or cite by symbol name instead.
- SDK candidate: yes

## RT-002 (medium) — agent_sdk/console/static/a2ui.js:28

- Quote: `const surfaces = new Map();`
- Description: The console's module-level surface registry was only pruned by `surfaces.delete(surfaceId)` in the deleteSurface branch. Now that the SDK emits no deleteSurface (GH-214), every artifact's entry stays in memory for the life of the page, holding components, the full dataModel copy and a DOM node reference. Nothing else ever clears it, so it grows without limit in a long console session, even after the transcript is cleared.
- Fix: Bound the registry: for example, drop an entry once it is painted and no further updates are expected, prune entries whose `entry.node` is no longer connected (`!entry.node.isConnected`) on each renderA2ui call, or clear the Map when the console starts a new conversation. Add a node-driven test (the harness pattern in tests/test_rt005_fund_performance_title.py) that renders N three-message arrays and asserts the registry size stays bounded.
- Codify: When a wire change removes the message a client used to free state (here deleteSurface), audit every first-party consumer for state that was only released by that message.
- SDK candidate: yes

## RT-003 (low) — tests/test_gh214_no_delete_surface.py:85

- Quote: `assert "msg.deleteSurface" in js`
- Description: The AC 'admin console still shows every surface in the transcript' is checked only by string greps over a2ui.js and chat.js. Nothing renders anything. The docstring is also wrong: it says a2ui.js 'only unmounts on a received deleteSurface', but a2ui.js never unmounts DOM, even on deleteSurface. The file paths are relative to the working directory, so the test breaks when pytest runs from another folder.
- Fix: Use the existing node harness (as in tests/test_rt005_fund_performance_title.py) to load a2ui.js and call renderA2ui with the three-message open sequence. Assert that one node comes back and that the surface stays open for later updates. Build the paths from Path(__file__).resolve().parents[1] and correct the docstring.
- SDK candidate: yes

## RT-004 (low) — agent_sdk/agent/runner.py:380

- Quote: `f"({payload.data_type!r}): translate() output split into "`
- Description: The error text in validate_a2ui_delivery still describes the removed split ('translate() output split into an empty open sequence (deleteSurface with no accompanying create/populate messages)'). The AC requires every deleteSurface mention in agent_sdk/ to use 'not emitted' or 'superseded' wording and the split wording to be gone.
- Fix: Reword it, for example: "translate() output has no open messages after dropping deleteSurface (never delivered, GH-214); malformed translate() output". Keep the 'empty open' substring so the rt004/rt001 `match=` assertions still pass.
- SDK candidate: yes

## RT-005 (low) — tests/test_gh214_no_delete_surface.py:67

- Quote: `monkeypatch.setattr(runner_module, "translate", lambda payload, **kw: [])`
- Description: test_empty_open_sequence_still_rejected feeds `[]`. That input is rejected by _validate_a2ui_wire's 'non-empty list' check before the new post-filter empty-open guard in validate_a2ui_delivery ever runs, so this GH-214 test never reaches the guard. It only re-tests SC-D1.
- Fix: Feed an all-deleteSurface list (for example `[{"version": "v0.9.1", "deleteSurface": {"surfaceId": "s"}}]`) and assert `match="empty open"` on both A2A build_artifact and AG-UI _RunMapper.map. Alternatively, add that case next to the `[]` case.
- SDK candidate: yes

## RT-006 (low) — tests/test_a2ui_wire.py:248

- Quote: `def test_split_a2ui_delivery_is_removed():`
- Description: Two tests, test_split_a2ui_delivery_isolates_delete_surface and test_split_a2ui_delivery_empty_input, were deleted and replaced by one hasattr check. The AC says tests that pinned the close message are rewritten, not deleted, to assert it is absent and to cite the ruling URL. The new test also has no ruling URL in its own docstring.
- Fix: Rewrite test_split_a2ui_delivery_isolates_delete_surface as an assertion that the delivered A2A/AG-UI arrays from a real translate() contain no deleteSurface and match translate() exactly. Keep the empty-input case as an empty-open rejection through validate_a2ui_delivery. Cite https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762 in each docstring.
- SDK candidate: yes

## RT-007 (low) — docs/protocols.md:53

- Quote: "one `A2UI_UPDATE`. Each turn uses a fresh `surfaceId`. The agent-card param"
- Description: docs/protocols.md, the translator.py module docstring (line 26), DESIGN.md §5.4/§7.1 and the CHANGELOG Migration callout all say 'each turn uses a fresh surfaceId'. In fact translate() makes a new uuid4 surfaceId for every artifact, so one turn with several artifacts has several surfaces. A client that keys lifetime per turn based on this text would collapse several cards into one. Separately, tests/test_rt001_a2ui_data_encoding_hint.py:6 (listed in G3 scope but not edited) still calls deleteSurfaceSemantics a live precedent.
- Fix: Say 'each artifact (A2A artifact / AG-UI A2UI_UPDATE) carries a fresh surfaceId' in docs/protocols.md, translator.py:26, DESIGN.md and the CHANGELOG Migration line. Mark the deleteSurfaceSemantics reference in tests/test_rt001_a2ui_data_encoding_hint.py's docstring as removed by GH-214.
- SDK candidate: yes
