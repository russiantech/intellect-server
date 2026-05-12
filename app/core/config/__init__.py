from typing import Optional
from .models import AppConfig
from .loader import ConfigLoader

_app_config: Optional[AppConfig] = None


def get_app_config() -> AppConfig:
    global _app_config
    if _app_config is None:
        _app_config = ConfigLoader().load_config()
    return _app_config


def reload_config() -> AppConfig:
    global _app_config
    _app_config = None
    return get_app_config()


app_config = get_app_config()

__all__ = ["AppConfig", "get_app_config", "reload_config", "app_config"]
