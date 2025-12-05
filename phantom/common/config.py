import os
import tomllib
from dataclasses import dataclass


@dataclass
class BotConfig:
    race = "Zerg"
    name = "PhantomBot"
    skip_first_iteration = False
    training = True
    debug_draw = False
    profile_interval = 100
    profile_path: str | None = None
    tag_log_level = "ERROR"
    build_order = "OVERHATCH"
    version_path = "version.txt"
    data_path = "./data"
    params_name = "params.pkl.xz"
    max_actions = 100

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
