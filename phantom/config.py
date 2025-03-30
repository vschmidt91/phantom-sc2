import os
import tomllib
from dataclasses import dataclass


@dataclass
class BotConfig:
    resign_after_iteration: int | None = None
    opponent_id: str | None = None
    training = False
    debug_draw = False
    test_ling_flood = False
    profile_path: str | None = None
    save_game_info: str | None = None
    tag_log_level = "ERROR"
    build_order = "HATCH_POOL_HATCH"

    version_path = "version.txt"
    data_path = "data"
    params_name = "params.pkl.xz"
    params_json_name = "params.json"

    @classmethod
    def from_toml(cls, path: str) -> "BotConfig":
        config = BotConfig()
        if os.path.isfile(path):
            with open(path, "rb") as config_file:
                config_dict: dict = tomllib.load(config_file)
        for key, value in config_dict.items():
            setattr(config, key, value)
        return config

    @property
    def params_path(self) -> str:
        return os.path.join(self.data_path, self.params_name)

    @property
    def params_json_path(self) -> str:
        return os.path.join(self.data_path, self.params_json_name)
