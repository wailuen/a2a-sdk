wave: w039
group: A
date: 2026-09-03
round_count: 5
status: budget-exhausted

## Findings

### RT-A01
- severity: high
- file: agent_sdk/models/content_types.py:208-235
- description: ContentModel.__init_subclass__'s back-compat rebinding causes infinite recursion for a pre-existing two-level domain-card hierarchy. A base card class overriding to_plain_text() and a child card calling super().to_plain_text() worked on v0.5.44; now both classes get to_plain_text rebound to ContentModel.to_plain_text, so the child's super() call re-enters the base implementation, which calls self._body_text(), which is the child's own function again -> RecursionError. Verified live: RecursionError. The docstring (line 221-225), CHANGELOG.md and docs/content-types.md all assert this cannot exist because 'super().to_plain_text() resolved to the abstract ... stub and returned None' — that is only true for a DIRECT ContentModel subclass, not for the documented domain-card hierarchy. RecursionError raised from runner.py:363 (TextPart(text=payload.to_plain_text())) fails the whole task.
- fix: Add a re-entrancy guard to ContentModel.to_plain_text (e.g. a per-instance/contextvar flag: if already inside, return self._body_text() without re-appending the suffix), or bind _body_text to a wrapper whose __globals__/super() target is the parent's _body_text rather than leaving the raw function in place. Add a regression test for a two-level legacy hierarchy (ContentModel -> DomainBase.to_plain_text -> DomainCard.to_plain_text calling super()); tests/ currently has none. Correct the three false 'no such code can exist' claims in the docstring, CHANGELOG and docs.
- codify: When back-compat-rebinding an overridden public method onto a new hook name, a subclass calling super().<old_name>() re-enters the rebound base and recurses — guard re-entry and test a two-level subclass hierarchy, not just a direct subclass.
- sdkCandidate: true

### RT-A02
- severity: high
- file: CHANGELOG.md:7-120
- description: Four of the five 🔴 Breaking changes in the 0.5.45 entry are voluntary redesigns of stable-core surfaces, shipped under a patch bump (v0.5.44 -> 0.5.45; pyproject.toml:7). DESIGN.md §4.0 line 141 states the wire-shape conformance exemption applies only when a break's 'sole purpose is bringing the SDK's wire output/parsing into conformance with an external protocol spec ... rather than a voluntary redesign' and that 'A voluntary breaking change to the stable core ... still requires a major bump; this exemption cannot be cited for those.' Only the fund_name removal is conformance-driven. The metadata hoist (changes wire key order for all 14 profile types + gives every external ContentModel subclass a field it never declared), the to_plain_text metadata suffix (changes the A2A TextPart at runner.py:363 and the MCP tools/call text at routes/mcp.py:363 for every card), the new @abc.abstractmethod _body_text on a documented public extension point (LRN-113, severity high — 'any new one requires a minor/major bump ... never a silent patch'), and the new non-finite-float rejection on metadata are all voluntary. §4.0 also lists 'Standard Profile contracts' as stable core.
- fix: Either bump to 0.6.0 for this release, or split the voluntary metadata/_body_text redesign out of 0.5.45 and ship only GH-149's conformance-driven fund_name removal under the §4.0 exemption. Do not cite §4.0 for the four voluntary bullets — the exemption text explicitly forbids it. Get developer ratification before tagging (this wave's own redteam cannot sign off a stable-core policy exception).
- codify: DESIGN.md §4.0's wire-shape conformance exemption covers only spec-driven breaks; a voluntary stable-core redesign shipped in the same release still needs a major bump, and bundling one with a conformance fix does not launder it.
- sdkCandidate: true

### RT-A03
- severity: medium
- file: agent_sdk/models/content_types.py:16-40
- description: The stated justification for the whole metadata/_body_text redesign is factually false, and is repeated in four places. The module docstring ('the suffix hand-appended at 14 subclass call sites, which the built-ins honoured and domain cards did not'), the ContentModel class docstring ('honoured by hand at 17 call sites in this module'), CHANGELOG.md and docs/content-types.md ('which the SDK's own 14 types honoured and domain cards did not') all claim built-in cards previously rendered metadata into to_plain_text(). Verified against `git show v0.5.44:agent_sdk/models/content_types.py`: all 15 occurrences of 'metadata' are field declarations; zero call sites, no built-in ever emitted it into the text fallback. The CHANGELOG contradicts itself two bullets earlier: 'before this release no type emitted metadata into its text fallback at all'. An operator reading these notes will mis-scope the impact as a domain-card-only fix rather than a text-fallback change affecting all 14 built-ins.
- fix: Rewrite the justification in all four locations to state what actually happened: metadata reached wire() but never to_plain_text() for ANY card, and this release starts emitting it for all of them. Keep the design decision; drop the invented prior-art.
- codify: A redteam-round justification comment is load-bearing documentation — verify a 'this was already the convention' claim against the last release tag before it is copied into the CHANGELOG and public docs.
- sdkCandidate: false

### RT-A04
- severity: medium
- file: .claude/agents/a2ui-advisor.md:279-285
- description: The frozen A2UI Standard Profile v1 field contract was edited inside a wave whose stated premise is that a frozen contract must not be silently extended. TimeSeriesChart's `| metadata | {identifier?, metric?, frequency?, source?} | — |` row was deleted from all three advisor copies (.claude/, harness/, template/) and replaced with a cross-cutting 'free-form, dict[str, Any] — no fixed sub-shape' note plus 'A conformance audit MUST NOT flag a type for having or lacking metadata'. That loosens a typed sub-shape to unconstrained and removes it from a2ui-check's conformance surface. GH-149's ACs authorize edits to content_types.py, catalog.py and a2ui.js only — the advisor tables are named as Reads-only ('parity check only, not modified'). DESIGN.md §4.0 lists 'Standard Profile contracts' as stable core. Separately, the content_types.py docstring claims the note appears 'verbatim' in each copy; it does not match the docstring's own wording ('cross-cutting' vs 'SDK-wide').
- fix: Revert the frozen-table edit or escalate it to the developer for explicit ratification before release (per the project's wave-self-signoff rule). If the loosening is intended, record it as a Standard Profile v1 contract change with its own version/breaking note rather than as a side effect of a field-removal issue. Fix the 'verbatim' claim in the content_types.py module docstring.
- codify: A wave may not edit the frozen A2UI Standard Profile tables to make code conformant — that inverts the contract; profile-table edits need their own issue and developer ratification, never a Reads-only file in the todo.
- sdkCandidate: true

### RT-A05
- severity: low
- file: agent_sdk/console/static/a2ui.js:226-255
- description: appendMetadataFootnote() renders every caller-/tool-supplied metadata key and value with no per-field length cap, no total cap, and no control-char strip — while its own comment claims it is 'exactly mirroring ContentModel.to_plain_text() appending _metadata_suffix() once on the base class'. The Python mirror (content_types.py:236-244) caps each key and value at 256 chars via sanitize_text (C-007, control-char strip) and bounds the assembled suffix to 4096. The console side has neither, so a metadata dict with thousands of keys or embedded C0/C1 control characters renders unbounded in the admin console (XSS is not reachable — el() uses createTextNode — but the two surfaces are not the mirror the comment asserts).
- fix: Cap the entry count and per-value length in appendMetadataFootnote (e.g. slice entries, truncate each rendered string to 256 chars with an ellipsis) and strip control chars, matching _METADATA_SUFFIX_FIELD_MAX_LEN / _METADATA_SUFFIX_MAX_LEN. Or amend the comment to state the console deliberately renders unbounded.
- codify: n/a
- sdkCandidate: false

### RT-A06
- severity: low
- file: CHANGELOG.md:82
- description: The 0.5.45 entry cites 'the same control-char-strip + length-cap discipline as agent/loop.py's _sanitize_model_name' as the reference for the new sanitize_text helper — but the same release DELETES _sanitize_model_name from loop.py (loop.py:63-70 records the deletion, and tests/test_rt002_c007_sanitize_text_single_definition.py:36 asserts `def _sanitize_model_name` is absent). A reader following the release note lands on a symbol that no longer exists.
- fix: Point the CHANGELOG line at agent_sdk.common.redact.sanitize_text (C-007) instead of the deleted private copy.
- codify: n/a
- sdkCandidate: false

### RT-A07
- severity: low
- file: agent_sdk/a2ui/catalog.py:44-51
- description: _own_annotation_names() swallows every exception with a bare `except Exception` and falls back to `vars(klass).get('__annotations__', {})` — the exact raw read its own docstring says is 'silently always-empty on 3.14' under PEP 649. On any unexpected failure the helper therefore returns a silently wrong answer (empty set) rather than a diagnosable one, which flips the declared_here test to False and drops a domain card's own redeclared metadata from the LLM-facing schema line with no signal. Same broad-except shape LRN-105 was logged for.
- fix: Narrow the except to the errors inspect.get_annotations can actually raise (NameError/TypeError/AttributeError), and log at DEBUG/WARNING when the fallback path is taken so the degraded summary is observable.
- codify: n/a
- sdkCandidate: false

## Instruction

Fix remaining findings, then re-run /wave w039.
