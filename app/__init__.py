import hmac
import os
import secrets
from pathlib import Path

from flask import Flask, abort, flash, redirect, request, session, url_for

from .db import init_app


def generate_csrf_token() -> str:
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


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
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB hard cap on uploads
    )

    if test_config:
        app.config.update(test_config)

    init_app(app)

    app.jinja_env.globals["csrf_token"] = generate_csrf_token

    from .views import bp

    app.register_blueprint(bp)

    @app.before_request
    def _csrf_check() -> None:
        if app.testing:
            return
        if request.method == "POST":
            token = request.form.get("_csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not expected or not hmac.compare_digest(token, expected):
                abort(403)

    @app.errorhandler(413)
    def upload_too_large(_err):
        flash("Upload rejected: file exceeds the 10 MB size limit.", "error")
        return redirect(url_for("moneyview.import_transactions")), 413

    return app
