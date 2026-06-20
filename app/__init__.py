import os
import secrets
from pathlib import Path

from flask import Flask

from .db import init_app


def _load_or_create_secret_key(data_dir: Path) -> str:
    if env_key := os.environ.get("SECRET_KEY", "").strip():
        return env_key

    key_file = data_dir / ".secret_key"
    data_dir.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()

    new_key = secrets.token_hex(32)
    key_file.write_text(new_key, encoding="utf-8")
    return new_key


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates")
    data_dir = Path(app.root_path).parent / "data"

    app.config.from_mapping(
        DATABASE_PATH=data_dir / "moneyview.sqlite3",
        SECRET_KEY=_load_or_create_secret_key(data_dir),
    )

    if test_config:
        app.config.update(test_config)

    init_app(app)

    from .views import bp

    app.register_blueprint(bp)
    return app
