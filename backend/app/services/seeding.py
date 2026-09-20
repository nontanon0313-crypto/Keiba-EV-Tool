"""Deterministic seed helper."""
import hashlib


def seed_for(s):
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)
