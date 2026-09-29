from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from lazycoder.config.exceptions import ConfigLoadError
from lazycoder.config.models import (
    AppConfig,
    EvalCase,
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


def fixtures_root(config_dir: Path) -> Path:
    """Fixture packs sit next to config/ (repo) or config_defaults/ (wheel)."""
    return config_dir.parent / "fixtures"


def load_fixture_cases(config_dir: Path, packs: list[str]) -> list[EvalCase]:
    """Assemble eval cases from fixtures/{pack}/cases.json.

    Packs are the source of truth.
    """
    root = fixtures_root(config_dir)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for pack in packs:
        path = root / pack / "cases.json"
        if not path.is_file():
            raise ConfigLoadError(path, "fixture pack cases.json is missing")
        data = _load_json(path)
        if not isinstance(data, list):
            raise ConfigLoadError(path, "fixture pack must be a JSON array of cases")
        for index, raw in enumerate(data):
            try:
                case = EvalCase.model_validate(raw)
            except ValidationError as exc:
                raise ConfigLoadError(
                    path, f"case[{index}]: {_format_validation_error(exc)}"
                ) from exc
            if case.id in seen:
                raise ConfigLoadError(path, f"duplicate case id {case.id}")
            seen.add(case.id)
            cases.append(case)
    if not cases:
        raise ConfigLoadError(root, "fixture packs produced no cases")
    return cases


def load_evals(config_dir: Path) -> EvalsConfig:
    """Load evals.json metadata, then fill cases from fixture packs (no dual source)."""
    path = config_dir / "evals.json"
    evals = load_config_file(path, EvalsConfig)
    if evals.cases:
        raise ConfigLoadError(
            path,
            "cases must not be embedded here; put them under fixtures/ and list "
            "fixture_packs (avoids dual-source drift)",
        )
    return evals.model_copy(
        update={"cases": load_fixture_cases(config_dir, evals.fixture_packs)}
    )


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
        evals=load_evals(root),
        observability=load_config_file(
            root / "observability.json", ObservabilityConfig
        ),
    )
