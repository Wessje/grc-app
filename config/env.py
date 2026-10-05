"""
Reads secret settings (such as SECRET_KEY and DEBUG) from the local `.env` file.

Keeping secrets in `.env` instead of in the code means they are never
committed to git. `.env.example` shows which settings are needed.
"""

import os
from pathlib import Path


def load_env_file(env_path: Path) -> None:
    """
    Load settings from a `.env` file into the process environment.

    Input: the path to the `.env` file. Each line looks like `NAME=value`;
    blank lines and lines starting with `#` are skipped.
    Output: nothing. Each setting is stored in `os.environ`, but a value that
    is already set in the environment is kept (so it can be overridden from
    Terminal without editing the file). A missing file is silently ignored.
    """
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def read_bool(name: str, default: bool = False) -> bool:
    """
    Read a yes/no setting from the environment.

    Input: the setting name and the value to use if it is not set.
    Output: True only for "true", "1" or "yes" (any capitalisation), so a
    typo falls back to False – the safer choice for settings like DEBUG.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes")
