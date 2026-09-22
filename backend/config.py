"""Keiba-EV-Tool 全体設定。"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    VOTE_MANAGER_URL: str = ""
    EV_THRESHOLD_TRIFECTA: float = 0.12
    EV_THRESHOLD_EXACTA: float = 0.10
    EV_THRESHOLD_TRIO: float = 0.08
    EV_THRESHOLD_WIDE: float = 0.05
    PL_TEMPERATURE: float = 1.0
    PL_MIN_PROB: float = 1e-6
    CALIB_WINDOW: int = 300
    CALIB_MIN_SAMPLES: int = 30
    DRIFT_WINDOW: int = 200
    DRIFT_THRESHOLD: float = 0.05
    MODEL_DIR: str = "models"
    LOG_DIR: str = "logs"
    LOG_LEVEL: str = "INFO"

    # 混在モード (複数券種から EV順で上位N点)
    MIXED_TICKETS: tuple = ("quinella", "trio", "wide")
    MIXED_EV_MIN: float = 0.5
    MIXED_ODDS_MIN: float = 30.0
    MIXED_TOP_N: int = 2

    # 賭け金モード (fixed / compound)
    BET_MODE: str = "compound"
    BET_COMPOUND_RATIO: float = 0.005  # 資金の0.5%
    BET_FIXED_UNIT: int = 500
    BET_BANKROLL_INIT: int = 50000

    JRAVAN_SID: str = ""
    JRAVAN_DATA_DIR: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
