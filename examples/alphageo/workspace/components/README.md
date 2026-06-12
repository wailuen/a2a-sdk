# Components index — AlphaGeo agent

Reusable components referenced by PRD FRs (`Reuses: C-NNN`).

| ID | Component | Location | Status |
|----|-----------|----------|--------|
| C-001 | `AlphaGeoSource` — source adapter with hybrid credential resolution | `src/sources/alphageo.py` | present |
| C-002 | `ClimateRiskReport` — A2UI domain content type (Standard Profile) | `src/content.py` | present |
| C-003 | `get_climate_risk_report` tool | `src/tools/climate.py` | present |
| C-004 | `EncryptedSqliteStore` credential store (SDK core) | `agent_sdk/credentials/store.py` | present (SDK) |
| C-005 | `ChatDriver` multi-turn test driver (SDK core) | `agent_sdk/testing/chat.py` | present (SDK) |
