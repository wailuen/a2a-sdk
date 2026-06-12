---
name: widget-briefing
description: How to produce a widget status briefing with KPI card
---

# Widget briefing

When the user asks for a widget overview or status briefing:

1. Call `get_widget` for the requested id to ground every claim.
2. Call `widget_kpis` for the same id so the client gets a KPI card.
3. Reply with two or three sentences: current status, the most notable
   metric, and any action the user should consider. Do not repeat the
   card's numbers in prose beyond the single most notable one.

Never invent metrics — if the API omits a field, say it is unavailable.
