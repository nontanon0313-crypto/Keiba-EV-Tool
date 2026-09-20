"""JRA-VAN adapter skeleton (JV-Link / JV-Data)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from backend.config import settings


@dataclass
class RaceCard:
    race_id: str
    date: str
    course: str
    race_no: int
    horses: List[dict] = field(default_factory=list)


class JRAVANAdapter:
    """Skeleton for JV-Link integration. Do not use in production yet."""

    def __init__(self, sid=None, data_dir=None):
        self.sid = sid or settings.JRAVAN_SID
        self.data_dir = data_dir or settings.JRAVAN_DATA_DIR

    @property
    def available(self):
        return bool(self.sid and self.data_dir)

    def _require(self):
        if not self.available:
            raise RuntimeError("JRAVAN_SID / JRAVAN_DATA_DIR not set")

    def fetch_race_cards(self, date):
        self._require()
        raise NotImplementedError("JV-Link race card fetch pending")

    def fetch_odds(self, race_id):
        self._require()
        raise NotImplementedError("JV-Link odds fetch pending")

    def fetch_results(self, race_id):
        self._require()
        raise NotImplementedError("JV-Link result fetch pending")

    def to_mock_format(self, cards):
        """Convert JV-Data cards into MockAdapter-compatible dicts."""
        return [c.__dict__ for c in cards]
