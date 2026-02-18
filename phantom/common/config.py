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
    build_order = "OVERPOOL"
    version_path = "version.txt"
    data_path = "./data"
    params_name = "params.pkl.xz"
    max_actions = 80
    optimizer_pop_size = 20
    roach_warren_cancel_enabled = False
    proxy_scout_enabled = True
    proxy_scout_max_overlords = 1
    proxy_scout_samples_max = 24

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
