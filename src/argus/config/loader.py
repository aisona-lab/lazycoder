from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from argus.config.exceptions import ConfigLoadError
from argus.config.models import (
    AppConfig,
    EvalsConfig,
    GuardrailsConfig,
    HarnessConfig,
    ObservabilityConfig,
    ProductionReadinessConfig,
    ReviewRulesConfig,
    SetupConfig,
    TaskLoopConfig,
    WorkingLoopConfig,
)

CONFIG_FILES: dict[str, type[BaseModel]] = {
    "harness.json": HarnessConfig,
    "guardrails.json": GuardrailsConfig,
    "setup.json": SetupConfig,
    "working_loop.json": WorkingLoopConfig,
    "task_loop.json": TaskLoopConfig,
    "review_rules.json": ReviewRulesConfig,
    "production_readiness.json": ProductionReadinessConfig,
    "evals.json": EvalsConfig,
    "observability.json": ObservabilityConfig,
}

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def _load_json(path: Path) -> object:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigLoadError(path, f"cannot read file ({exc})") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(
            path, f"invalid JSON at line {exc.lineno}: {exc.msg}"
        ) from exc


def load_config_file[T: BaseModel](path: Path, model: type[T]) -> T:
    """Load and validate a single config file against its pydantic schema."""
    data = _load_json(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigLoadError(path, _format_validation_error(exc)) from exc


def load_all_configs(config_dir: Path | None = None) -> AppConfig:
    """Load and validate every config JSON. Fails loudly on the first error."""
    root = config_dir or DEFAULT_CONFIG_DIR
    if not root.is_dir():
        raise ConfigLoadError(root, "config directory does not exist")

    for filename in CONFIG_FILES:
        path = root / filename
        if not path.is_file():
            raise ConfigLoadError(path, "config file is missing")

    return AppConfig(
        harness=load_config_file(root / "harness.json", HarnessConfig),
        guardrails=load_config_file(root / "guardrails.json", GuardrailsConfig),
        setup=load_config_file(root / "setup.json", SetupConfig),
        working_loop=load_config_file(root / "working_loop.json", WorkingLoopConfig),
        task_loop=load_config_file(root / "task_loop.json", TaskLoopConfig),
        review_rules=load_config_file(root / "review_rules.json", ReviewRulesConfig),
        production_readiness=load_config_file(
            root / "production_readiness.json", ProductionReadinessConfig
        ),
        evals=load_config_file(root / "evals.json", EvalsConfig),
        observability=load_config_file(
            root / "observability.json", ObservabilityConfig
        ),
    )
