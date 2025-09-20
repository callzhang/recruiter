from pydantic import BaseModel
import os

class Settings(BaseModel):
    BASE_URL: str = os.getenv("BASE_URL", "https://www.zhipin.com")
    STORAGE_STATE: str = os.getenv("STORAGE_STATE", "data/state.json")
    HEADLESS: bool = os.getenv("HEADLESS", "False").lower() == "true"
    SLOWMO_MS: int = int(os.getenv("SLOWMO_MS", "50"))
    CLICK_DELAY_RANGE: str = os.getenv("CLICK_DELAY_RANGE", "400,1200")  # 毫秒范围，逗号分隔
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "data/output")

settings = Settings()

def click_delay_range_ms():
    a, b = settings.CLICK_DELAY_RANGE.split(",")
    return int(a), int(b)
