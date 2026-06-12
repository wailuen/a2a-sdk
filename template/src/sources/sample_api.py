"""Sample SourceAdapter — replace with your real upstream (/add-source).

All outbound HTTP for a source goes through its adapter: the base class
enforces ``allowed_hosts`` on every hop, owns timeouts and the retry-once
policy, and maps upstream failures to redacted ``AgentError``s. Tools never
construct HTTP clients.
"""

from __future__ import annotations

from typing import Any

from agent_sdk import SourceAdapter
from agent_sdk.validation import url_segment


class SampleApiAdapter(SourceAdapter):
    source_name = "sample_api"
    allowed_hosts = ["api.example.com"]

    @property
    def base_url(self) -> str:
        return "https://api.example.com/v1"

    def _headers(self) -> dict[str, str]:
        # Resolved from this source's namespace in the encrypted store;
        # configured via the admin console. Never read env vars here.
        return {"Authorization": f"Bearer {self.credential('api_token')}"}

    async def get_widget(self, widget_id: str) -> dict[str, Any]:
        # url_segment(): user-derived path params are validated + encoded,
        # never f-stringed raw into a URL.
        resp = await self.get(
            f"{self.base_url}/widgets/{url_segment(widget_id)}",
            headers=self._headers(),
        )
        return resp.json()

    async def health_check(self) -> bool:
        try:
            await self.get(f"{self.base_url}/ping", headers=self._headers())
            return True
        except Exception:
            return False
