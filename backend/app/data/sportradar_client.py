import httpx
import asyncio
from typing import Any
from ..core.config import get_settings
from ..core.cache import cache_get, cache_set

settings = get_settings()

_RATE_LIMIT_DELAY = 1.0  # Sportradar trial: 1 req/sec


class SportradarClient:
    def __init__(self):
        self.base_url = settings.sportradar_base_url
        self.api_key = settings.sportradar_api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _get(self, endpoint: str, cache_ttl: int = 3600) -> dict[str, Any]:
        cache_key = f"sportradar:{endpoint}"
        cached = await cache_get(cache_key)
        if cached:
            return cached

        url = f"{self.base_url}/{endpoint}.json"
        client = await self._get_client()
        await asyncio.sleep(_RATE_LIMIT_DELAY)

        response = await client.get(url, params={"api_key": self.api_key})
        response.raise_for_status()
        data = response.json()

        await cache_set(cache_key, data, ttl=cache_ttl)
        return data

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # --- League endpoints ---

    async def get_league_hierarchy(self) -> dict:
        return await self._get("league/hierarchy", cache_ttl=86400)

    async def get_season_schedule(self, year: int, season_type: str = "REG") -> dict:
        return await self._get(f"games/{year}/{season_type}/schedule", cache_ttl=3600)

    async def get_standings(self, year: int, season_type: str = "REG") -> dict:
        return await self._get(f"seasons/{year}/{season_type}/standings/division", cache_ttl=3600)

    # --- Team endpoints ---

    async def get_team_roster(self, team_id: str) -> dict:
        return await self._get(f"teams/{team_id}/profile", cache_ttl=3600)

    async def get_team_stats(self, team_id: str, year: int, season_type: str = "REG") -> dict:
        return await self._get(f"seasons/{year}/{season_type}/teams/{team_id}/statistics", cache_ttl=3600)

    # --- Player endpoints ---

    async def get_player_profile(self, player_id: str) -> dict:
        return await self._get(f"players/{player_id}/profile", cache_ttl=7200)

    async def get_player_stats(self, player_id: str, year: int, season_type: str = "REG") -> dict:
        return await self._get(f"players/{player_id}/profile", cache_ttl=3600)

    # --- Game endpoints ---

    async def get_game_boxscore(self, game_id: str) -> dict:
        return await self._get(f"games/{game_id}/boxscore", cache_ttl=300)

    async def get_game_summary(self, game_id: str) -> dict:
        return await self._get(f"games/{game_id}/summary", cache_ttl=300)

    async def get_daily_schedule(self, year: int, month: int, day: int) -> dict:
        return await self._get(f"games/{year}/{month:02d}/{day:02d}/schedule", cache_ttl=600)

    # --- Free agency / transactions ---

    async def get_free_agents(self, year: int) -> dict:
        return await self._get(f"league/{year}/free_agents", cache_ttl=3600)

    async def get_transactions(self, year: int, month: int, day: int) -> dict:
        return await self._get(f"league/{year}/{month:02d}/{day:02d}/transactions", cache_ttl=3600)


# Module-level singleton
_client: SportradarClient | None = None


def get_sportradar() -> SportradarClient:
    global _client
    if _client is None:
        _client = SportradarClient()
    return _client
