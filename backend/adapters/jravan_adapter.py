"""JRA-VAN adapter (JV-Link + JV-Data)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from backend.config import settings
from backend.adapters.jvdata_parser import parse_lines
from backend.adapters.jvlink_client import make_default_client


@dataclass
class RaceCard:
    race_id: str
    date: str
    course: str
    race_no: int
    horses: List[dict] = field(default_factory=list)


class JRAVANAdapter:
    def __init__(self, sid=None, data_dir=None, client=None):
        self.sid = sid or settings.JRAVAN_SID
        self.data_dir = data_dir or settings.JRAVAN_DATA_DIR
        self._client = client

    @property
    def available(self):
        return bool(self.sid and self.data_dir)

    def _client_or_raise(self):
        if not self.available:
            raise RuntimeError("JRAVAN_SID / JRAVAN_DATA_DIR not set")
        if self._client is None:
            self._client = make_default_client(self.sid, self.data_dir)
        return self._client

    def _read_records(self, dataspec, fromtime):
        client = self._client_or_raise()
        client.open(dataspec, fromtime, 1)
        try:
            lines = list(client.read())
        finally:
            client.close()
        return parse_lines(lines)

    def fetch_race_cards(self, date):
        parsed = self._read_records("RACE", date)
        return [RaceCard(r.race_id, r.date, r.course, r.race_no) for r in parsed["races"]]

    def fetch_odds(self, race_id):
        self._client_or_raise()
        raise NotImplementedError("odds fetch pending")

    def fetch_results(self, race_id):
        self._client_or_raise()
        raise NotImplementedError("result fetch pending")

    def to_mock_format(self, cards):
        return [c.__dict__ for c in cards]
