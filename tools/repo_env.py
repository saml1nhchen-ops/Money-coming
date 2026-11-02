"""Load simple repository-local environment settings without logging secrets."""
import os
import pathlib
import re


def load_repo_env(path=None):
    # Allows hermetic tools/tests to avoid accessing local credentials entirely.
    if os.environ.get('SIGNAL_LOAD_DOTENV', '1') == '0':
        return
    path = pathlib.Path(path) if path is not None else pathlib.Path(__file__).resolve().parents[1] / '.env'
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name, value = name.strip(), value.strip()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(name, value)
