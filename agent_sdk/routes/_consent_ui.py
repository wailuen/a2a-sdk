"""Shared layout for the OAuth consent pages (admin-key and IdP sign-in).

One self-contained HTML document: inline ``<style>`` and an inline SVG mark
only, because the pages are served under ``_CONSENT_SECURITY_HEADERS``
(``default-src 'none'; style-src 'unsafe-inline'``): no scripts, images, fonts
or external styles can load. Light/dark follows ``prefers-color-scheme``; on a
narrow screen the card fills the width and the buttons stack.

Every caller-supplied value is HTML-escaped by the helpers here; ``form_html``
is the only pre-built markup and is assembled by oauth.py from escaped parts.
"""

from __future__ import annotations

import html

from ._tpc_logo import TPC_LOGO_SVG

_CSS = """
:root { color-scheme: light dark;
  --bg: #f3f4f6; --card: #ffffff; --border: #e5e7eb; --text: #111827;
  --muted: #4b5563; --label: #374151; --foot: #f9fafb; --foot-border: #f3f4f6;
  --accent: #1d4ed8; --on-accent: #ffffff; --btn2: #ffffff; --btn2-border: #d1d5db;
  --err: #b91c1c; --input-border: #d1d5db; }
@media (prefers-color-scheme: dark) { :root {
  --bg: #0b0f17; --card: #151a23; --border: #2a3140; --text: #f3f4f6;
  --muted: #9ca3af; --label: #d1d5db; --foot: #11151d; --foot-border: #2a3140;
  --accent: #93c5fd; --on-accent: #0b0f17; --btn2: transparent; --btn2-border: #3a4252;
  --err: #fca5a5; --input-border: #3a4252; } }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center;
  justify-content: center; padding: 24px 16px; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif; }
main { width: 440px; max-width: 100%; background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(17,24,39,0.04), 0 8px 24px rgba(17,24,39,0.06); }
.head { padding: 28px 32px 0; display: flex; align-items: center; gap: 14px; }
.logo { width: 35px; height: 48px; flex: none; display: block; }
.agent { font-size: 15px; font-weight: 600; }
.sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
.intro { padding: 24px 32px 0; }
h1 { margin: 0 0 8px; font-size: 22px; line-height: 1.3; font-weight: 600; }
.who { margin: 0; font-size: 14px; line-height: 1.5; color: var(--muted); overflow-wrap: anywhere; }
.who strong { color: var(--text); font-weight: 600; }
.can { margin: 20px 32px 0; padding: 16px; border: 1px solid var(--border); border-radius: 8px; }
.can-title { font-size: 13px; font-weight: 600; color: var(--label); margin-bottom: 12px; }
.can ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.can li { display: flex; gap: 10px; align-items: flex-start; font-size: 14px; line-height: 1.45; }
.tick { width: 18px; height: 18px; flex: none; margin-top: 1px; }
dl { margin: 16px 32px 0; display: grid; grid-template-columns: 96px minmax(0, 1fr);
  row-gap: 8px; column-gap: 12px; font-size: 13px; line-height: 1.45; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
form { margin: 24px 32px 0; }
.err { margin: 0 0 12px; font-size: 14px; color: var(--err); }
.note { margin: 0 0 12px; font-size: 13px; color: var(--muted); }
input[type=password] { width: 100%; height: 44px; padding: 0 12px; margin-bottom: 12px;
  border: 1px solid var(--input-border); border-radius: 8px; background: var(--card);
  color: var(--text); font: inherit; font-size: 15px; }
.actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.actions.one { grid-template-columns: minmax(0, 1fr); }
button { height: 44px; border-radius: 8px; font: inherit; font-size: 15px; cursor: pointer; }
.primary { border: 1px solid var(--accent); background: var(--accent); color: var(--on-accent);
  font-weight: 600; }
.secondary { border: 1px solid var(--btn2-border); background: var(--btn2); color: var(--text);
  font-weight: 500; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.foot { margin: 20px 0 0; padding: 14px 32px 18px; border-top: 1px solid var(--foot-border);
  background: var(--foot); font-size: 12px; line-height: 1.5; color: var(--muted); }
@media (max-width: 480px) {
  body { padding: 0; align-items: stretch; }
  main { border: none; border-radius: 0; box-shadow: none; }
  .head, .intro { padding-left: 20px; padding-right: 20px; }
  .can, dl, form { margin-left: 20px; margin-right: 20px; }
  .foot { padding-left: 20px; padding-right: 20px; }
  dl { grid-template-columns: minmax(0, 1fr); row-gap: 2px; }
  dd { margin-bottom: 8px; }
  .actions { grid-template-columns: minmax(0, 1fr); }
  .actions .primary { order: -1; }
  button { height: 48px; font-size: 16px; }
}
"""

_TICK = (
    '<svg class="tick" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true" style="color: var(--accent)"><path d="M20 6 9 17l-5-5"></path></svg>'
)

_CAN_DO = (
    "Use this agent’s tools on your behalf",
    "See the results those tools return",
)


def render_consent_page(
    *,
    agent_name: str,
    client_name: str,
    return_host: str,
    audience: str,
    form_action: str,
    form_html: str,
    allow_label: str = "Allow",
    signed_in_as: str | None = None,
    error: str | None = None,
) -> str:
    """Build the consent document. ``form_action`` is a server constant and
    ``form_html`` (hidden fields, inputs, buttons) is pre-escaped markup built
    by the caller; every other string is a raw value and is escaped here."""
    agent = html.escape(agent_name)
    client = html.escape(client_name)
    who = (
        f'<p class="who">Signed in as <strong>{html.escape(signed_in_as)}</strong></p>'
        if signed_in_as
        else ""
    )
    error_html = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    can = "\n".join(f"<li>{_TICK}<span>{html.escape(item)}</span></li>" for item in _CAN_DO)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Authorize access — {agent}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<div class="head">
{TPC_LOGO_SVG}
<div><div class="agent">{agent}</div><div class="sub">Sign-in request · Built by TPC</div></div>
</div>
<div class="intro">
<h1>{client} wants to access {agent}</h1>
{who}
</div>
<div class="can">
<div class="can-title">If you allow, this app can:</div>
<ul>
{can}
</ul>
</div>
<dl>
<dt>App</dt><dd>{client}</dd>
<dt>Returns to</dt><dd>{html.escape(return_host)}</dd>
<dt>Resource</dt><dd class="mono">{html.escape(audience)}</dd>
</dl>
<form method="post" action="{form_action}">
{error_html}
{form_html}
</form>
<p class="foot">Only continue if you started this from {client}. Nothing is shared until you choose {html.escape(allow_label)}.</p>
</main>
</body>
</html>
"""
