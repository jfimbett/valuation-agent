import os
from pathlib import Path


def load_env(path: Path = Path(__file__).resolve().parent.parent / ".env") -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
