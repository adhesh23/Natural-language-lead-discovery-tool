"""Small persistent counters for APIs with daily request caps."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable


DEFAULT_COUNTER_PATH = Path("data") / "api_request_counts.json"


class DailyRequestCounter:
    """Persist per-provider request counts and reset them on a new local day."""

    def __init__(
        self,
        path: str | Path = DEFAULT_COUNTER_PATH,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.path = Path(path)
        self._today = today

    def try_acquire(self, provider: str, limit: int) -> bool:
        """Consume one request slot, or return ``False`` when the daily cap is met."""

        if limit < 1:
            return False
        current_day = self._today().isoformat()
        data = self._load()
        if data.get("date") != current_day:
            data = {"date": current_day, "counts": {}}

        counts = data.setdefault("counts", {})
        current_count = counts.get(provider, 0)
        if not isinstance(current_count, int) or current_count >= limit:
            return False
        counts[provider] = current_count + 1
        self._save(data)
        return True

    def count(self, provider: str) -> int:
        """Return today's stored count for a provider without consuming a slot."""

        data = self._load()
        if data.get("date") != self._today().isoformat():
            return 0
        count = data.get("counts", {}).get(provider, 0)
        return count if isinstance(count, int) else 0

    def _load(self) -> dict[str, object]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        temporary_path.replace(self.path)
