"""JV-Data fixed-length parser (skeleton)."""
from __future__ import annotations
from dataclasses import dataclass


def _slice(line, start, length):
    return line[start - 1: start - 1 + length].strip()


@dataclass
class RaceInfo:
    race_id: str
    date: str
    course: str
    race_no: int


@dataclass
class HorseEntry:
    race_id: str
    horse_id: str
    horse_name: str
    waku: int
    num: int
    jockey: str


def parse_ra(line):
    return RaceInfo(race_id=_slice(line, 4, 16), date=_slice(line, 20, 8), course=_slice(line, 28, 2), race_no=int(_slice(line, 30, 2) or "0"))


def parse_se(line):
    return HorseEntry(race_id=_slice(line, 4, 16), horse_id=_slice(line, 12, 10), horse_name=_slice(line, 41, 36), waku=int(_slice(line, 4, 1) or "0"), num=int(_slice(line, 9, 2) or "0"), jockey=_slice(line, 297, 8))


def parse_lines(lines):
    races = []
    entries = []
    for line in lines:
        tag = line[:2]
        if tag == "RA":
            races.append(parse_ra(line))
        elif tag == "SE":
            entries.append(parse_se(line))
    return {"races": races, "entries": entries}
