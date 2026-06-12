---
name: climate-briefing
description: How to produce a climate-risk briefing for a property or location
---

# Climate-risk briefing

When the user asks about a property's or location's climate risk:

1. Default to `alphageo_get_full_report` — one call covers every period and
   hazard, plus financial impact and resilience. Pass the full address
   including the country.
2. For a single year with every dimension, use
   `alphageo_get_climate_profile`. For one narrow question (just scores, just
   physical data, just resilience, or just financial impact), use the matching
   single tool.
3. The tool emits a structured Climate Risk Report card. Reply with at most
   three sentences: the key risk insight, an actionable recommendation, and —
   for multiple properties — comparison context. Do not restate the card's
   numbers in prose.

If a section comes back unavailable (it appears in the report's section
errors), say so plainly rather than guessing. Never invent scores or hazards
the tools did not return.
