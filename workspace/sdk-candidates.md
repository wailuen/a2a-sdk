# SDK issue candidates — w063 (2026-10-24)

These critical/high findings from wave w063 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: In the admin console, a failed resume POST for a multi-field interrupt cannot be retried. The submit handler removes the interrupt form before sending. On failure, the code puts pendingInterrupt back but does not show the form again. Typed text then goes to buildResumePayload, which says 'this interrupt needs several fields; use the form', but there is no form on the page. The user is stuck. The fix: show the form again (interruptForm(resumed) when formFields(...) is not null) and reset the input placeholder, or keep the form until the POST succeeds.
- Severity: high
- Component: sdk/console
- File: agent_sdk/console/static/chat.js
- Status: fixed-in-wave
- Rationale: agent_sdk/console/static/chat.js is the SDK's own admin test console code, shared by every agent. The bug is in SDK internals, not in any one agent's domain code. The other RT-001 finding (CHANGELOG.md naming) was left out because it is about the wave's own release notes, and this is the a2a-sdk repo itself.
