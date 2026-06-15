# w013 — stack-check punch-list (COMPLIANT maintenance)

Sourced from /agent-stack-check punch-list after v0.5.4 release. All items independent.
Run in parallel (group:A).
Target: v0.5.5.

---

- [ ] `A2A-F1` A2A server: wrong error code on terminal-task message/send ‖ group:A
  - Creates: (modifies `agent_sdk/routes/a2a.py`)
  - Reads: `agent_sdk/routes/a2a.py`, `tests/test_a2a_error_envelope.py`
  - Severity: medium
  - Root cause: `message/send` to a terminal task returns -32002 (TaskNotCancelable). Per A2A §2
    error code table, -32002 maps exclusively to tasks/cancel. The correct code is -32004
    (UnsupportedOperation — operation not valid in current task state).
  - AC-1: `a2a.py` terminal-task path returns `A2A_UNSUPPORTED_OPERATION` (-32004), not -32002
  - AC-2: `tests/test_a2a_error_envelope.py` asserts -32004 on message/send to a completed task

- [ ] `AG-UI-F-M-01` AG-UI consumer: history message content uses flat string ‖ group:A
  - Creates: (modifies `agent_sdk/console/static/chat.js`)
  - Reads: `agent_sdk/console/static/chat.js`, `agent_sdk/routes/ag_ui.py`
  - Severity: medium
  - Root cause: User messages in aguiMessages history use `content: text` (flat string).
    AG-UI canonical multimodal shape is `content: [{type:"text", text}]`. Server _fold_history
    handles both, but canonical form eliminates divergence and future-proofs multimodal payloads.
  - AC-1: `chat.js` user message history entries use `content: [{type: "text", text: <value>}]`
  - AC-2: Existing routing/parity test still passes

- [ ] `A2UI-F1` A2UI: system prompt does not inject Profile v1 field contracts ‖ group:A
  - Creates: (modifies `agent_sdk/a2ui/catalog.py` or new `agent_sdk/a2ui/prompt.py`;
    modifies `agent_sdk/app.py`)
  - Reads: `agent_sdk/a2ui/catalog.py`, `agent_sdk/a2ui/translator.py`, `agent_sdk/app.py`,
    `agent_sdk/models/content_types.py`
  - Severity: low
  - Root cause: `app.py` assembles system_prompt from persona + skills.catalog_text() with no
    A2UI wire-contract guidance. LLMs producing tool outputs for registered content types receive
    no prompt-level constraint on PascalCase component names or required fields.
  - AC-1: `agent_sdk/a2ui/` exports `get_system_prompt_section()` returning a concise
    wire-contract summary for all registered FROZEN types
  - AC-2: `app.py` appends this section to system_prompt when A2UI content types are registered
  - AC-3: New test asserts the section is non-empty when at least one content type is registered
