"""
app/__init__.py
TrustPulse Flask application factory
"""

from flask import Flask
from pathlib import Path


def create_app():
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parents[1] / "templates"),
        static_folder=str(Path(__file__).resolve().parents[1] / "static"),
    )

    app.config["SECRET_KEY"] = "trustpulse-dev-key"

    # Register custom Jinja2 filters
    app.jinja_env.filters['enumerate'] = enumerate

    from app.routes import main
    app.register_blueprint(main)

    return app
