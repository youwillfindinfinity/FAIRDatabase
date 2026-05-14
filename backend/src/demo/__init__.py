"""Demo blueprint."""

from flask import Blueprint

routes = Blueprint("demo", __name__)

# Import routes to register them with the blueprint
from src.demo import routes  # noqa: F401, E402