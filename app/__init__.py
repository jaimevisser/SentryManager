from __future__ import annotations

from importlib import import_module

__all__ = ["app"]


def __getattr__(name: str):
	if name != "app":
		raise AttributeError(name)
	return import_module(".frontend.app", __name__).app

__all__ = ["app"]
