import json
import os
from pydantic import BaseModel
from typing import Optional

CONFIG_FILE = "data/config.json"

class AppConfig(BaseModel):
    emby_host: str = ""
    api_key: str = ""
    user_id: str = ""
    scan_interval: int = 5
    batch_size: int = 0  # 0 means unlimited
    exclude_paths: str = ""

    class Config:
        json_schema_extra = {
            "example": {
                "emby_host": "http://192.168.1.100:8096",
                "api_key": "your_api_key",
                "user_id": "your_user_id",
                "scan_interval": 5,
                "batch_size": 0,
                "exclude_paths": "/mnt/user/115/\n/mnt/user/aliyun/"
            }
        }

def load_config() -> AppConfig:
    if not os.path.exists(CONFIG_FILE):
        return AppConfig()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return AppConfig(**data)
    except Exception as e:
        print(f"Error loading config: {e}")
        return AppConfig()

def save_config(config: AppConfig):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(config.model_dump_json(indent=4))
