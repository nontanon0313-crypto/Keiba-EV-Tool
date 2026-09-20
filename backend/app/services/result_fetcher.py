import random
from backend.app.services.seeding import seed_for


def fetch_result(race_id, num_runners=18):
    rng = random.Random(seed_for("result:" + race_id))
    nums = list(range(1, num_runners + 1))
    rng.shuffle(nums)
    return nums[:3]
