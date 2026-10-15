wave: w050
scope: group
group: G3
date: 2026-10-15

Non-blocking — these did not block w050's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G3. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/agent/loop.py
- description: The GH-176 boot check (and the GH-172 case rules) only guard classes passed to register_content_type. The runtime path never checks that an emitted ContentModel's class is registered: loop.py:1722 accepts any isinstance(result, emits) subclass, and translator.translate() writes type(payload).component straight onto the wire. Confirmed by probe: `class Card(KpiCard): component = "Card"`, returned from a tool declaring emits=KpiCard, produces updateComponents component "Card", which is the Basic Catalog primitive the ruling says must refuse to boot.
- fix: Close the subclass hole at one point. build_app()._validate_emits cannot see it (the subclass is only known at run time), so in loop.py before yielding ArtifactEvent (or in runner.build_artifact) require `content_type_for(type(result).data_type) is type(result)`; otherwise fall back to the text-only/raw path or raise a fixed-text error. Alternatively run the name rules from ContentModel.__init_subclass__ for any subclass that overrides component. Add a test that a subclass named Card/checkbox never reaches the wire.
- codify: A name rule enforced only at register time is bypassable when the emit path accepts unregistered subclasses; the wire must only carry registered component classes.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in three rounds. The GH-176 ruling (issue 176 comment 6187889280) and the CHANGELOG entry both say "The error names the card and the clash". The new Basic Catalog primitive error (around line 1544), the RESERVED casefold errors (1511-1515, 1536-1541) and the PascalCase error/hint (1505-1510) give only the component string and the clashing name. They never name the registering class (`cls.__name__`) or its data_type. A probe registering `class ClimateRiskCard` with component='Card' got: "component name 'Card' equals the Basic Catalog primitive 'Card' ignoring case; ...", with no 'ClimateRiskCard' in it — it names the clash twice and never says which card is at fault. An agent that registers many cards, builds them from a factory, or reuses a component string cannot tell from the boot error which class failed. tests/test_gh176_basic_catalog_names.py checks only `repr(name)`, so this gap passes the tests.
- fix: Add `{cls.__name__}` (and data_type) to the primitive-clash, RESERVED and PascalCase ValueError messages, e.g. f"{cls.__name__}: component name {component!r} equals the Basic Catalog primitive {primitive!r} ignoring case ...". Extend test_basic_primitive_refused to assert that the test class's `__name__` (e.g. '_Card') and 'Basic Catalog primitive' both appear in the message.
- codify: When a ruling says an error 'names the card', the test must assert that the class name appears in the message, not only the offending value.
- sdkCandidate: true

### RT-003
- severity: medium
- file: harness/skills/add-tool/SKILL.md
- description: The new boot-time refusal of the 18 Basic Catalog primitive names was not added to the guidance that downstream authors read. harness/skills/add-tool/SKILL.md:92-94 (and its byte-identical mirror template/.claude/skills/add-tool/SKILL.md) tells authors only to avoid Standard Profile names. DESIGN.md:231 says register_content_type "refuses the four RESERVED names" and does not mention primitives, PascalCase, or case-folded clashes. An agent built with /add-tool can still pick `Card`, `List` or `Text` and fail at boot after upgrading.
- fix: Update harness/skills/add-tool/SKILL.md and template/.claude/skills/add-tool/SKILL.md to say the component must be PascalCase and must not equal, ignoring case, a RESERVED name, a Basic Catalog primitive (`BASIC_CATALOG_COMPONENTS`), or an already registered name. Update DESIGN.md:231 the same way and cite GH-176.
- codify: A new boot-time registration rule must update DESIGN.md and the harness skill that tells downstream authors how to name the thing, in the same wave.
- sdkCandidate: true

### RT-004
- severity: medium
- file: workspace/components/README.md
- description: Raised in three rounds. BASIC_CATALOG_COMPONENTS (agent_sdk/models/content_types.py:161) is a new reusable profile-data constant and now a third copy of the 18 primitive names. The other two are the lists in .claude/agents/a2ui-advisor.md and harness/agents/a2ui-advisor.md. No test ties the copies together. The todo's Reuses: C-021 note asked for the constant to live with the A2UI catalog/profile data; it landed in content_types.py, which is justified (agent_sdk/a2ui/catalog.py imports content_types, so the reverse would be circular), but the deviation is not recorded anywhere. The C-021 StandardProfileV1Contract entry was not updated and no new entry points at the constant, so the copies can drift.
- fix: Update the C-021 registry entry (or add one) to name agent_sdk.models.content_types.BASIC_CATALOG_COMPONENTS (and RESERVED_COMPONENTS) as the in-code source of truth, and record why they live there, so the planned profile.py moves them rather than adding another copy. Add a small test that parses the advisor docs' primitive list and checks it equals the constant, or change the advisor docs to point at the constant. Optionally re-export BASIC_CATALOG_COMPONENTS from agent_sdk/a2ui/catalog.py.
- sdkCandidate: true

### RT-005
- severity: low
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds. Against the todo's Reuses: C-021 note ("Extend the existing GH-172 casefold loop ... over RESERVED_COMPONENTS + BASIC_CATALOG_COMPONENTS. Do not add a second loop."), the landed code adds a separate `for primitive in BASIC_CATALOG_COMPONENTS` loop (lines 1542-1548) next to the RESERVED loop and the registered-name loop. A new helper, `_case_clash_hint` (1481-1493), then walks the same three lists a fourth time. That gives two copies of the clash rule that can drift: for example, the hint checks registered names first-match while the loops order RESERVED, primitive, registered.
- fix: Add one helper, `_case_clash(cls, component) -> tuple[kind, name] | None`, that walks RESERVED_COMPONENTS + BASIC_CATALOG_COMPONENTS + registered names once and returns the first clash. Use it both for the PascalCase-error hint and for the casefold refusal in register_content_type, so a single loop holds the rule.
- sdkCandidate: true

### RT-006
- severity: low
- file: tests/test_gh176_basic_catalog_names.py
- description: Raised in two rounds. Test coverage is thin and partly self-satisfying. Only 3 exact or mixed-case primitives (Card, Text, Textfield) plus a few lowercase names are tried, not all 18. All-caps or mixed-case variants of every primitive (e.g. `CARD`, `Datetimeinput`, which pass the PascalCase regex and reach only the primitive loop) are not tested, so a regression in the loop's casefold logic for multi-word names would not be caught. The match=clash check for 'Card' and 'Text' would pass on any ValueError that echoes the component name, so it does not prove the primitive branch fired. A falsy non-string component (component=0) still raises TypeError('must declare data_type and component'), not the documented ValueError, and nothing covers that case.
- fix: Parametrize over BASIC_CATALOG_COMPONENTS. For each name, assert that the exact name and name.upper() (plus .swapcase()/.capitalize() where still PascalCase) raise a ValueError containing 'Basic Catalog primitive' and naming that primitive. Add a component=0 case: either change the `not component` guard to `component is None` so 0 reaches the ValueError branch, or document the TypeError.
- sdkCandidate: true
