from pathlib import Path

from flask import Flask

from .db import init_app


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config.from_mapping(
        DATABASE_PATH=Path(app.root_path).parent / "data" / "moneyview.sqlite3",
        SECRET_KEY="moneyview-dev",
    )

    if test_config:
        app.config.update(test_config)

    init_app(app)

    from .views import bp

    app.register_blueprint(bp)
    return app