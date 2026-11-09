"""Importing app does not initialize runtime data; app.main is the ASGI entry."""
from .factory import create_app

__all__ = ["create_app"]
