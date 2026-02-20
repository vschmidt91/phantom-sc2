import json
from pathlib import Path

import numpy as np

from phantom.counters.mlp_composition import TinyMLPComposition


def save_model_json(model: TinyMLPComposition, path: str | Path) -> None:
    payload = {
        "w1": model.w1.tolist(),
        "b1": model.b1.tolist(),
        "w2": model.w2.tolist(),
        "b2": model.b2.tolist(),
    }
    Path(path).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def load_model_json(path: str | Path) -> TinyMLPComposition:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TinyMLPComposition(
        w1=np.asarray(payload["w1"], dtype=np.float64),
        b1=np.asarray(payload["b1"], dtype=np.float64),
        w2=np.asarray(payload["w2"], dtype=np.float64),
        b2=np.asarray(payload["b2"], dtype=np.float64),
    )
