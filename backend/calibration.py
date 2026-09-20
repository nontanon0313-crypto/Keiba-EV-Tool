"""確率キャリブレーション (Platt scaling)。"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from backend.config import settings


def _sigmoid(x):
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1.0 - p))


@dataclass
class PlattCalibrator:
    a: float = 1.0
    b: float = 0.0
    fitted: bool = False
    n_samples: int = 0

    def fit(self, probs, labels, lr=0.1, epochs=300):
        xs = [_logit(p) for p in probs]
        ys = [float(y) for y in labels]
        if len(xs) < settings.CALIB_MIN_SAMPLES:
            return self
        for _ in range(epochs):
            ga = gb = 0.0
            for x, y in zip(xs, ys):
                p = _sigmoid(self.a * x + self.b)
                err = p - y
                ga += err * x
                gb += err
            n = len(xs)
            self.a -= lr * ga / n
            self.b -= lr * gb / n
        self.fitted = True
        self.n_samples = len(xs)
        return self

    def transform(self, p):
        if not self.fitted:
            return p
        return _sigmoid(self.a * _logit(p) + self.b)

    def to_dict(self):
        return {"a": self.a, "b": self.b, "fitted": self.fitted, "n_samples": self.n_samples}

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


@dataclass
class CalibrationStore:
    history: list = field(default_factory=list)
    calibrator: PlattCalibrator = field(default_factory=PlattCalibrator)

    def add(self, prob, hit):
        self.history.append((float(prob), int(hit)))
        if len(self.history) > settings.CALIB_WINDOW:
            self.history = self.history[-settings.CALIB_WINDOW:]

    def refit(self):
        if len(self.history) < settings.CALIB_MIN_SAMPLES:
            return self.calibrator
        ps, ys = zip(*self.history)
        self.calibrator = PlattCalibrator().fit(ps, ys)
        return self.calibrator
