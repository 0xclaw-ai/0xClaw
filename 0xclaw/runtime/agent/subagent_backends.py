"""Backend selection and adapters for subagents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger
from runtime.agent.claude_code_executor import ClaudeCodeProvider
from runtime.config.schema import SubagentsConfig
from runtime.providers.base import LLMProvider, LLMResponse


@dataclass(slots=True)
class SubagentTaskContext:
    """Task context used to resolve a subagent backend."""

    phase: str | None
    label: str | None
    task: str


@dataclass(slots=True)
class SubagentBackendDecision:
    """Resolved backend choice for a subagent run."""

    requested_backend: str
    actual_backend: str
    provider: LLMProvider
    fallback_reason: str | None = None

    @property
    def display_name(self) -> str:
        return self.actual_backend


def _build_claude_code_provider(
    *,
    config: SubagentsConfig,
    default_model: str,
    phase: str = "coding",
) -> ClaudeCodeProvider:
    return ClaudeCodeProvider(config.claude_code, default_model=default_model, phase=phase)


def _phase_policy(config: SubagentsConfig, phase: str | None):
    """Return the per-phase backend policy (CodingSubagentConfig / TestingSubagentConfig) or None."""
    if not phase:
        return None
    return getattr(config, phase, None)


class DefaultLLMSubagentProvider(LLMProvider):
    """Thin wrapper over the existing provider for default subagent execution."""

    def __init__(self, inner: LLMProvider):
        super().__init__(api_key=getattr(inner, "api_key", None), api_base=getattr(inner, "api_base", None))
        self._inner = inner

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        return await self._inner.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )

    def get_default_model(self) -> str:
        return self._inner.get_default_model()

    async def close(self) -> None:  # pragma: no cover - no-op by design
        return None


def is_coding_subagent(context: SubagentTaskContext) -> bool:
    """Return True when the task is the coding-phase coder subagent."""

    if context.phase != "coding":
        return False

    label = (context.label or "").lower()
    task = context.task.lower()
    if label.startswith("coder") or "coder agent" in task or "负责实现" in context.task:
        return True
    return False


def resolve_subagent_backend(
    *,
    context: SubagentTaskContext,
    default_provider: LLMProvider,
    default_model: str,
    config: SubagentsConfig,
) -> SubagentBackendDecision:
    """Resolve the backend for a subagent run with safe fallback behavior."""

    requested = "default_llm"
    if is_coding_subagent(context):
        requested = config.coding.backend or "default_llm"

    if requested == "default_llm":
        return SubagentBackendDecision(
            requested_backend=requested,
            actual_backend="default_llm",
            provider=DefaultLLMSubagentProvider(default_provider),
        )

    if requested == "claude_code":
        provider = _build_claude_code_provider(config=config, default_model=default_model)
        ok, message = provider.preflight()
        if ok:
            logger.info(
                "Subagent backend selected: requested={} actual={} phase={} label={}",
                requested, requested, context.phase, context.label or "",
            )
            return SubagentBackendDecision(
                requested_backend=requested,
                actual_backend="claude_code",
                provider=provider,
            )

        fallback = config.coding.fallback_backend or "default_llm"
        logger.warning(
            "Subagent backend fallback: requested={} actual={} reason={}",
            requested, fallback, message,
        )
        return SubagentBackendDecision(
            requested_backend=requested,
            actual_backend=fallback,
            provider=DefaultLLMSubagentProvider(default_provider),
            fallback_reason=message,
        )

    reason = f"Unknown subagent backend: {requested}"
    logger.warning(reason)
    fallback = config.coding.fallback_backend or "default_llm"
    return SubagentBackendDecision(
        requested_backend=requested,
        actual_backend=fallback,
        provider=DefaultLLMSubagentProvider(default_provider),
        fallback_reason=reason,
    )


def resolve_phase_backend(
    *,
    phase: str | None,
    default_provider: LLMProvider,
    default_model: str,
    config: SubagentsConfig,
) -> SubagentBackendDecision:
    """Resolve the backend for a top-level phase execution.

    Reads ``config.<phase>.backend`` (and ``fallback_backend``) for any phase
    that has a per-phase policy attached to ``SubagentsConfig`` (today: coding
    and testing). Phases without a policy fall back to ``default_llm``.
    """

    policy = _phase_policy(config, phase)
    requested = (getattr(policy, "backend", None) or "default_llm") if policy else "default_llm"
    fallback_backend = (
        getattr(policy, "fallback_backend", None) or "default_llm"
    ) if policy else "default_llm"

    if requested == "default_llm":
        return SubagentBackendDecision(
            requested_backend=requested,
            actual_backend="default_llm",
            provider=DefaultLLMSubagentProvider(default_provider),
        )

    if requested == "claude_code":
        provider = _build_claude_code_provider(
            config=config, default_model=default_model, phase=phase or "coding",
        )
        ok, message = provider.preflight()
        if ok:
            logger.info(
                "Phase backend selected: requested={} actual={} phase={}",
                requested, requested, phase,
            )
            return SubagentBackendDecision(
                requested_backend=requested,
                actual_backend="claude_code",
                provider=provider,
            )

        logger.warning(
            "Phase backend fallback: requested={} actual={} phase={} reason={}",
            requested, fallback_backend, phase, message,
        )
        return SubagentBackendDecision(
            requested_backend=requested,
            actual_backend=fallback_backend,
            provider=DefaultLLMSubagentProvider(default_provider),
            fallback_reason=message,
        )

    reason = f"Unknown phase backend: {requested}"
    logger.warning(reason)
    return SubagentBackendDecision(
        requested_backend=requested,
        actual_backend=fallback_backend,
        provider=DefaultLLMSubagentProvider(default_provider),
        fallback_reason=reason,
    )
