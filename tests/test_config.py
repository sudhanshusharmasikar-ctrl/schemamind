"""Settings come from a .env file in the project folder, and the shell wins over it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "app" / "config.py"


def read_config(tmp_path, expr, dotenv=None, **shell):
    """Evaluate `expr` on a copy of app/config.py in an empty folder, so the real
    project's .env (if you have one) and your shell can't affect the result."""
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    shutil.copy(CONFIG, tmp_path / "app" / "config.py")
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SCHEMAMIND_", "MISTRAL_"))}
    env.update(shell)
    out = subprocess.run(
        [sys.executable, "-c", f"from app import config; print({expr})"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )
    return out.stdout.split()


def test_dotenv_is_read_and_a_shell_variable_overrides_it(tmp_path):
    out = read_config(tmp_path, "config.TOP_K_TABLES, config.GEN_MODE, config.MISTRAL_API_KEY",
                      dotenv="SCHEMAMIND_TOP_K_TABLES=4\nSCHEMAMIND_GEN_MODE=mistral\nMISTRAL_API_KEY=k-123\n",
                      SCHEMAMIND_GEN_MODE="template")  # set in the shell, so it beats the file
    assert out == ["4", "template", "k-123"]


def test_without_a_dotenv_the_defaults_apply(tmp_path):
    out = read_config(tmp_path, "config.GEN_MODE, repr(config.MISTRAL_API_KEY)")
    assert out == ["template", "''"]
