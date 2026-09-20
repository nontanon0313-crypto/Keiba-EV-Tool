import random
from backend.app.services.seeding import seed_for


def fetch_result(race_id, num_runners=18, prediction=None):
    rng = random.Random(seed_for("result:" + race_id))
    if prediction is not None and getattr(prediction, "trifecta_probs", None):
        tps = prediction.trifecta_probs
        if tps:
            weights = [max(t.prob, 1e-9) * rng.uniform(0.4, 2.0) for t in tps]
            total = sum(weights)
            r = rng.uniform(0, total)
            acc = 0.0
            for w, t in zip(weights, tps):
                acc += w
                if r <= acc:
                    parts = t.combo.split("-")
                    try:
                        return [int(parts[0]), int(parts[1]), int(parts[2])]
                    except (ValueError, IndexError):
                        break
    nums = list(range(1, num_runners + 1))
    rng.shuffle(nums)
    return nums[:3]
