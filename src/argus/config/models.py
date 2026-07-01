from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.domain.enums import RuleId, Severity, Verdict

RuleCategory = Literal[
    "code_level",
    "correctness",
    "security",
    "simplicity",
    "maintainability",
    "tests",
    "compatibility",
    "system_level",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- harness.json ---


class HarnessProject(_StrictModel):
    name: str
    codename: str
    description: str
    owner: str
    version: str


class HarnessStack(_StrictModel):
    language: str
    llm: str
    orchestration: str
    data: str
    rationale: str


class HarnessConventions(_StrictModel):
    style: str
    numbers: str
    commits: str
    diffs: str


class HarnessCommands(_StrictModel):
    install: str
    run: str
    test: str
    lint: str
    types: str


class HarnessConfig(_StrictModel):
    schema_: str | None = Field(default=None, alias="$schema")
    project: HarnessProject
    stack: HarnessStack
    structure: dict[str, str]
    conventions: HarnessConventions
    hard_rules: list[str] = Field(min_length=1)
    commands: HarnessCommands
    definition_of_done: list[str] = Field(min_length=1)


# --- guardrails.json ---


class SecretHandling(_StrictModel):
    never_log_secrets: bool
    never_send_secrets_to_llm: bool
    redact_patterns: list[str] = Field(min_length=1)


class PromptInjectionDefense(_StrictModel):
    principle: str
    ignore_embedded_instructions: bool
    never_execute_reviewed_code_outside_sandbox: bool
    quote_and_flag_suspicious_instructions: bool


class SandboxConfig(_StrictModel):
    required_for_execution: bool
    network: str
    filesystem: str


class HumanInTheLoop(_StrictModel):
    required_for: list[str] = Field(min_length=1)
    escalate_if: list[str] = Field(min_length=1)


class GuardrailLimits(_StrictModel):
    max_steps_per_review: int = Field(gt=0)
    max_files_per_run: int = Field(gt=0)
    max_tokens_budget: int = Field(gt=0)


class GuardrailsConfig(_StrictModel):
    default_posture: str
    allowed_actions: list[str] = Field(min_length=1)
    forbidden_without_human_approval: list[str] = Field(min_length=1)
    secret_handling: SecretHandling
    prompt_injection_defense: PromptInjectionDefense
    sandbox: SandboxConfig
    human_in_the_loop: HumanInTheLoop
    limits: GuardrailLimits


# --- setup.json ---


class RuntimeConfig(_StrictModel):
    python: str


class DependenciesConfig(_StrictModel):
    required: list[str] = Field(min_length=1)
    rationale: dict[str, str]


class SetupConfig(_StrictModel):
    runtime: RuntimeConfig
    dependencies: DependenciesConfig
    env_vars: dict[str, str]
    files_to_create: list[str] = Field(min_length=1)
    bootstrap_steps: list[str] = Field(min_length=1)


# --- working_loop.json ---


class WorkingLoopStep(_StrictModel):
    id: str
    action: str
    output: str | None = None
    gate: str | None = None
    note: str | None = None


class ErrorHandling(_StrictModel):
    on_tool_failure: str
    on_uncertainty: str
    on_guardrail_trigger: str


class WorkingLoopConfig(_StrictModel):
    name: str
    principle: str
    steps: list[WorkingLoopStep] = Field(min_length=1)
    error_handling: ErrorHandling
    stop_conditions: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)


# --- task_loop.json ---


class OrchestratorConfig(_StrictModel):
    role: str
    never: str


class SubagentConfig(_StrictModel):
    role: str
    applies_rule_ids: list[RuleId] = Field(min_length=1)
    context: str | None = None
    focus: str | None = None


class TaskLoopRules(_StrictModel):
    isolated_context_per_subagent: bool
    no_shared_mutable_state: bool
    each_finding_must_cite_rule_id_and_location: bool
    orchestrator_verifies_between_steps: bool
    conflicting_findings_resolved_by_orchestrator: bool
    subagent_tools_are_least_privilege: bool


class AggregationConfig(_StrictModel):
    verdict_policy: str
    dedupe_findings: bool
    order_findings_by: str


class TaskLoopConfig(_StrictModel):
    name: str
    orchestrator: OrchestratorConfig
    subagents: list[SubagentConfig] = Field(min_length=1)
    rules: TaskLoopRules
    aggregation: AggregationConfig


# --- review_rules.json ---


class ReviewRule(_StrictModel):
    id: RuleId
    category: RuleCategory
    question: str
    checks: str
    good_answer: str
    flag_when: str
    severity_if_unjustified: Severity
    note: str | None = None


class ReviewRulesConfig(_StrictModel):
    description: str
    verdicts: list[Verdict]
    severity_levels: list[Severity]
    categories: dict[str, str]
    rules: list[ReviewRule] = Field(min_length=1)


# --- production_readiness.json ---


class ReadinessChecklistItem(_StrictModel):
    id: str
    area: str
    item: str
    pass_when: str


class ProductionReadinessConfig(_StrictModel):
    description: str
    checklist: list[ReadinessChecklistItem] = Field(min_length=1)
    release_policy: str


# --- evals.json ---


class ExpectedFinding(_StrictModel):
    rule_id: RuleId
    reason: str


class EvalCase(_StrictModel):
    id: str
    name: str
    input_code: str
    expect_findings: list[ExpectedFinding]
    expect_verdict: Verdict
    note: str | None = None


class EvalScoring(_StrictModel):
    pass_case_when: str
    report: str


class EvalsConfig(_StrictModel):
    description: str
    principle: str
    cases: list[EvalCase] = Field(min_length=1)
    scoring: EvalScoring


# --- observability.json ---


class DecisionLogConfig(_StrictModel):
    storage: str
    record_per_run: list[str] = Field(min_length=1)


class TracingConfig(_StrictModel):
    trace_each_subagent_step: bool
    capture_real_tool_output: bool
    no_self_reported_success: bool


class LoggingConfig(_StrictModel):
    format: str
    levels: list[str] = Field(min_length=1)
    redact: list[str] = Field(min_length=1)


class ObservabilityConfig(_StrictModel):
    description: str
    decision_log: DecisionLogConfig
    tracing: TracingConfig
    logging: LoggingConfig
    metrics: list[str] = Field(min_length=1)


# --- aggregate ---


class AppConfig(_StrictModel):
    harness: HarnessConfig
    guardrails: GuardrailsConfig
    setup: SetupConfig
    working_loop: WorkingLoopConfig
    task_loop: TaskLoopConfig
    review_rules: ReviewRulesConfig
    production_readiness: ProductionReadinessConfig
    evals: EvalsConfig
    observability: ObservabilityConfig
