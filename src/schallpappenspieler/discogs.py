import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class DiscogsRateLimit:
    limit: Optional[int]
    used: Optional[int]
    remaining: Optional[int]


class DiscogsClient:
    def __init__(self, token: str, user_agent: str):
        self._token = token
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Discogs token={token}",
                "User-Agent": user_agent,
            }
        )
        self.last_rate: Optional[DiscogsRateLimit] = None

    def _update_rate(self, headers) -> DiscogsRateLimit:
        def _to_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        rate = DiscogsRateLimit(
            limit=_to_int(headers.get("X-Discogs-Ratelimit")),
            used=_to_int(headers.get("X-Discogs-Ratelimit-Used")),
            remaining=_to_int(headers.get("X-Discogs-Ratelimit-Remaining")),
        )
        self.last_rate = rate
        return rate

    def wait_if_limited(self) -> int:
        if not self.last_rate or self.last_rate.remaining is None:
            return 0
        if self.last_rate.remaining > 0:
            return 0
        sleep_seconds = 60
        time.sleep(sleep_seconds)
        return sleep_seconds

    def search_cover(self, track: str, artist: Optional[str]) -> Optional[str]:
        params = {
            "track": track,
            "type": "release",
            "per_page": 5,
        }
        if artist:
            params["artist"] = artist

        max_retries = 2
        for attempt in range(max_retries + 1):
            resp = self._session.get(
                "https://api.discogs.com/database/search",
                params=params,
                timeout=15,
            )
            self._update_rate(resp.headers)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait_seconds = int(retry_after) if retry_after else 60
                except ValueError:
                    wait_seconds = 60
                time.sleep(wait_seconds)
                continue
            resp.raise_for_status()

            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None
            return results[0].get("cover_image")
        return None
