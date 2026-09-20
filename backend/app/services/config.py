import os
from dotenv import load_dotenv
load_dotenv()
EV_THRESHOLD_3RENTAN = float(os.getenv("EV_THRESHOLD_3RENTAN", "0.12"))
EV_THRESHOLD_UMAREN = float(os.getenv("EV_THRESHOLD_UMAREN", "0.07"))
BUDGET = int(os.getenv("BUDGET", "2000"))
CALIBRATION_ENABLED = os.getenv("CALIBRATION_ENABLED", "false").lower() == "true"
VOTE_MANAGER_URL = os.getenv("VOTE_MANAGER_URL", "")
