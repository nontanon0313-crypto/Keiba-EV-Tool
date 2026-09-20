"""モデルドリフト検知。"""
from __future__ import annotations
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from backend.config import settings


@dataclass
class DriftSample:
    predicted: float
    actual: int
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ChangeDetector:
    window: int = settings.DRIFT_WINDOW
    threshold: float = settings.DRIFT_THRESHOLD
    samples: deque = field(default_factory=deque)

    def __post_init__(self):
        self.samples = deque(self.samples, maxlen=self.window)

    def add(self, predicted, actual):
        self.samples.append(DriftSample(float(predicted), int(actual)))

    def status(self):
        n = len(self.samples)
        if n < 20:
            return {"drift": False, "reason": "insufficient_data", "n": n}
        preds = [s.predicted for s in self.samples]
        actuals = [s.actual for s in self.samples]
        mean_p = statistics.fmean(preds)
        mean_a = statistics.fmean(actuals)
        diff = mean_a - mean_p
        return {"drift": abs(diff) > self.threshold, "n": n, "mean_predicted": mean_p, "mean_actual": mean_a, "diff": diff, "threshold": self.threshold}

    def reset(self):
        self.samples.clear()
