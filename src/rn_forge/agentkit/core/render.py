"""Strict Jinja rendering utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError

from .io import dumps_config


class RenderError(ValueError):
    """Raised when a configuration template cannot be rendered."""


class RenderEngine:
    """Render configuration templates with strict undefined handling."""

    def __init__(self, template_dir: Path | None = None) -> None:
        loader = FileSystemLoader(str(template_dir)) if template_dir else None
        self.environment = Environment(
            loader=loader,
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        self.environment.filters["to_toml"] = lambda value: dumps_config(value, "toml")
        self.environment.filters["to_yaml"] = lambda value: dumps_config(value, "yaml")

    def render_string(self, template: str, context: dict[str, Any]) -> str:
        try:
            return self.environment.from_string(template).render(**context)
        except TemplateError as exc:
            raise RenderError(str(exc)) from exc

    def render_template(self, name: str, context: dict[str, Any]) -> str:
        try:
            return self.environment.get_template(name).render(**context)
        except TemplateError as exc:
            raise RenderError(str(exc)) from exc

    def validate_templates(self) -> list[str]:
        """Compile all templates visible to the loader and return errors."""
        errors: list[str] = []
        try:
            names = self.environment.list_templates()
        except TypeError:
            return errors
        for name in names:
            try:
                self.environment.get_template(name)
            except TemplateError as exc:
                errors.append(f"{name}: {exc}")
        return errors
