from __future__ import annotations

import httpx

import token_store
import config_store as _config_store
from config import get_settings

_DEFAULT_REDUNDANCY = 0.25


class ServerClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def _base(self) -> str:
        return token_store.get_server_url() or self._settings.SERVER_URL

    @property
    def _auth_headers(self) -> dict[str, str]:
        token = self._settings.AGENT_SERVICE_TOKEN or token_store.get_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def register(
        self,
        peer_id: str,
        api_url: str,
        udp_host: str,
        udp_port: int,
        transport: str = "udp",
        owner: str | None = None,
    ) -> dict:
        body: dict = {
            "peer_id": peer_id,
            "api_url": api_url,
            "udp_host": udp_host,
            "udp_port": udp_port,
            "transport": transport,
            "relay_capable": self._settings.RELAY_CAPABLE,
            "relay_tags": [t.strip() for t in self._settings.RELAY_TAGS.split(",") if t.strip()],
            "owner": owner or self._settings.PEER_OWNER or None,
        }
        try:
            invite = _config_store.get("invite_token", "") or self._settings.INVITE_TOKEN
            body["network_hint"] = _config_store.get("network_hint", self._settings.NETWORK_HINT)
        except Exception:
            invite = self._settings.INVITE_TOKEN
            body["network_hint"] = self._settings.NETWORK_HINT
        if invite:
            body["invite_token"] = invite
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.post(
                f"{self._base}/peers/register",
                json=body,
                headers=self._auth_headers,
            )
            r.raise_for_status()
            return r.json()

    async def heartbeat(self, peer_id: str) -> None:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as c:
            r = await c.post(
                f"{self._base}/peers/{peer_id}/heartbeat",
                headers=self._auth_headers,
            )
            r.raise_for_status()

    async def get_peers(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(f"{self._base}/peers", headers=self._auth_headers)
            r.raise_for_status()
            return r.json()

    async def get_peer(self, peer_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(f"{self._base}/peers/{peer_id}", headers=self._auth_headers)
            if r.status_code == 404:
                raise ValueError(f"Peer {peer_id!r} not found on server")
            r.raise_for_status()
            return r.json()

    async def report_metrics(
        self, peer_id: str, rtt_ms: float, jitter_ms: float, loss_rate: float, target_peer_id: str = "server"
    ) -> None:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as c:
            await c.post(
                f"{self._base}/metrics/report",
                json={
                    "peer_id": peer_id,
                    "target_peer_id": target_peer_id,
                    "rtt_ms": rtt_ms,
                    "jitter_ms": jitter_ms,
                    "loss_rate": loss_rate
                },
                headers=self._auth_headers,
            )

    async def get_full_recommendation(self, peer_id: str) -> dict:
        """Returns {redundancy_level, quality, profile_name, based_on_samples}."""
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as c:
                r = await c.get(
                    f"{self._base}/metrics/recommendation/{peer_id}",
                    headers=self._auth_headers,
                )
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return {
            "redundancy_level": _DEFAULT_REDUNDANCY,
            "quality": "unknown",
            "profile_name": "unknown",
            "based_on_samples": 0,
        }

    async def get_recommendation(self, peer_id: str) -> float:
        rec = await self.get_full_recommendation(peer_id)
        return rec["redundancy_level"]

    async def get_transit_decision(
        self, source: str, target: str, relays: list[str] | None = None
    ) -> dict:
        """Ask the server's Jev layer for the transit decision source→target.

        Returns {redundancy_level, quality, should_relay, relay_peer_id,
        source_name, confidence, ...}. Safe fallback to the static
        recommendation if the Jev endpoint is unavailable.
        """
        params = {"relay": relays} if relays else None
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
                r = await c.get(
                    f"{self._base}/jev/transit/{source}/{target}",
                    params=params,
                    headers=self._auth_headers,
                )
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "redundancy_level": data.get("redundancy_level",
                                                       _DEFAULT_REDUNDANCY),
                        "quality": data.get("quality"),
                        "profile_name": data.get("profile_name"),
                        "should_relay": data.get("should_relay", False),
                        "relay_peer_id": data.get("relay_peer_id"),
                        "source_name": data.get("source_name", "deterministic"),
                        "confidence": data.get("confidence"),
                        "based_on_samples": data.get("based_on_samples", 0),
                    }
        except Exception:
            pass
        return {
            "redundancy_level": _DEFAULT_REDUNDANCY,
            "quality": "unknown",
            "profile_name": "unknown",
            "should_relay": False,
            "relay_peer_id": None,
            "source_name": "deterministic",
            "confidence": None,
            "based_on_samples": 0,
        }

    async def get_incoming_policy(self, peer_id: str) -> dict:
        """Fetch the server-side incoming policy for this peer (admin-configured)."""
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as c:
            r = await c.get(
                f"{self._base}/peers/{peer_id}/incoming-policy",
                headers=self._auth_headers,
            )
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()

    async def get_relay_for_peer(self, target_id: str) -> dict:
        """Ask the server for the best relay peer to reach target_id."""
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as c:
            r = await c.get(
                f"{self._base}/peers/relay",
                params={"target": target_id},
                headers=self._auth_headers,
            )
            if r.status_code == 404:
                raise ValueError(f"No relay available for target {target_id!r}")
            r.raise_for_status()
            return r.json()


server_client = ServerClient()
