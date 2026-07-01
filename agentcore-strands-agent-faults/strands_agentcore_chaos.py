"""strands_agentcore_chaos: chaos engineering for Strands Agents on AgentCore Runtime.

A single, self-contained module that a customer drops into their agent and wires
in with one import::

    from strands import Agent
    from strands_agentcore_chaos import chaos_plugins

    agent = Agent(model=..., tools=[...], plugins=chaos_plugins())

Including this module in a build is the coarse "chaos is loaded" toggle; AWS SSM
Parameter Store (``/chaos/{runtime_id}/*``) is the fine, per-invocation switch
driven by an FIS-orchestrated experiment. Every invocation is a no-op until SSM
reports ``active=true``. A production-pure build simply omits this module
entirely, so it carries zero chaos surface.

This module bridges SSM-driven runtime config to the ``_current_chaos_case``
ContextVar that the reused, unmodified ``strands_evals.chaos.ChaosPlugin``
already reads; it adds only a controller, a TTL-cached loader, a case builder,
and runtime-ID resolution.

Public surface:
- ``chaos_plugins()``       one-line integration: controller + ChaosPlugin.
- ``RuntimeChaosController``the Strands plugin that drives per-invocation faults.
- ``RuntimeChaosConfig``    the cached configuration snapshot.
- ``resolve_runtime_id()``  resolves the AgentCore runtime ID for SSM scoping.
- ``build_chaos_case()``    builds a validated ChaosCase from raw config.
- ``SSMConfigLoader``       TTL-cached, fail-closed SSM Parameter Store reader.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import urllib.parse
from contextvars import Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from pydantic import TypeAdapter
from strands.hooks import AfterInvocationEvent, BeforeInvocationEvent
from strands.plugins import Plugin, hook
from strands_evals.chaos import ChaosCase, ChaosPlugin
from strands_evals.chaos.effects import ToolEffectUnion

# Re-export the EXACT ContextVar object the reused ChaosPlugin reads. Importing
# the name directly (rather than the module) makes an upstream rename fail loudly
# at import time, rather than silently degrading to a controller that arms a
# ContextVar the plugin never reads (Requirements 6.7, 6.8). The controller sets
# and reads this same object so a case it arms is the case the plugin observes
# within the same invocation.
from strands_evals.chaos._context import _current_chaos_case

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    from botocore.client import BaseClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached configuration snapshot
# ---------------------------------------------------------------------------
@dataclass
class RuntimeChaosConfig:
    """A cached snapshot of the chaos configuration for one runtime.

    Produced by :class:`SSMConfigLoader` from the ``/chaos/{runtime_id}/*``
    parameters. The default-constructed instance is the fail-closed no-op
    configuration: chaos inactive, no fault rate, and no case armed.

    Attributes:
        active: Whether chaos is active for this snapshot.
        fault_rate: Probability in ``[0.0, 1.0]`` that an invocation is faulted.
        case: A single pre-built and validated ``ChaosCase``, or ``None``.
        execution_id: The SSM Automation execution ID, for per-run correlation.
            (FIS does not expose its own experiment ID to action parameters, so
            the Automation document writes its own execution ID instead.)
        fetched_at: ``time.monotonic()`` value when this snapshot was fetched.
    """

    active: bool = False
    fault_rate: float = 0.0
    case: Optional[ChaosCase] = None
    execution_id: str = ""
    fetched_at: float = 0.0

    @classmethod
    def no_op(cls, fetched_at: Optional[float] = None) -> "RuntimeChaosConfig":
        """Return the fail-closed no-op configuration.

        Used whenever the control plane must fail closed (SSM read error,
        malformed/out-of-range parameters, or an absent/false ``active`` flag):
        chaos is inactive and no case is armed, so invocations run as if no
        chaos plugins were registered.

        Args:
            fetched_at: Optional monotonic timestamp to stamp on the snapshot.
                Defaults to ``time.monotonic()`` so the no-op result is cached
                with a fresh fetch time.
        """
        return cls(fetched_at=time.monotonic() if fetched_at is None else fetched_at)


# ---------------------------------------------------------------------------
# Runtime-ID resolution
# ---------------------------------------------------------------------------
# The runtime ID is the segment immediately following "runtime/". The trailing
# "/" guards against matching "runtimes/" (the URL path) or "runtime-endpoint/".
_RUNTIME_ID_RE = re.compile(r"runtime/([^/]+)")


def resolve_runtime_id() -> str:
    """Resolve this agent's AgentCore runtime ID by source precedence.

    Resolution precedence (Requirement 5.3):
      1. ``AGENT_RUNTIME_ID`` -- explicit operator-injected override (recommended:
         fully under operator control and portable to ECS/Lambda).
      2. ``AGENTCORE_RUNTIME_URL`` -- the runtime ARN is URL-encoded in this
         variable's path; the ID is the segment after ``runtime/`` once decoded.
      3. ``cloud.resource_id`` within ``OTEL_RESOURCE_ATTRIBUTES`` -- present when
         observability is enabled (the default).

    The returned value scopes the ``/chaos/{runtime_id}/`` SSM subtree and equals
    the ``RuntimeId`` parameter passed to the ``ChaosExperiment`` SSM document --
    that equality wires one FIS experiment to exactly one runtime (Req 5.5).

    Returns:
        The resolved runtime ID, suitable as the ``/chaos/{runtime_id}/`` SSM
        prefix and the FIS ``RuntimeId`` parameter.

    Raises:
        RuntimeError: If none of the supported sources resolve (fail closed,
            Requirement 5.4).
    """
    # Source 1: explicit operator override.
    rid = os.environ.get("AGENT_RUNTIME_ID", "").strip()
    if rid:
        return rid

    # Source 2: runtime ARN URL-encoded in AGENTCORE_RUNTIME_URL.
    url = urllib.parse.unquote(os.environ.get("AGENTCORE_RUNTIME_URL", ""))
    match = _RUNTIME_ID_RE.search(url)
    if match:
        return match.group(1)

    # Source 3: cloud.resource_id within OTEL_RESOURCE_ATTRIBUTES.
    attrs = dict(
        pair.split("=", 1)
        for pair in os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",")
        if "=" in pair
    )
    match = _RUNTIME_ID_RE.search(attrs.get("cloud.resource_id", ""))
    if match:
        return match.group(1)

    # Fail closed: no source resolved (Requirement 5.4).
    raise RuntimeError(
        "cannot resolve AgentCore runtime id; set AGENT_RUNTIME_ID explicitly"
    )


# ---------------------------------------------------------------------------
# Chaos-case builder
# ---------------------------------------------------------------------------
# Deserialises a list of effect dicts into concrete effect instances via the
# Pydantic discriminated union keyed by ``effect_type``. Unknown effect types
# raise ``pydantic.ValidationError``. Built once and reused.
_EFFECT_LIST_ADAPTER: TypeAdapter[list[ToolEffectUnion]] = TypeAdapter(list[ToolEffectUnion])


def build_chaos_case(raw: str, execution_id: str) -> ChaosCase | None:
    """Build a validated ``ChaosCase`` from a raw ``fault_injections`` JSON string.

    Supports exactly the seven v1 tool-level effect types (``timeout``,
    ``network_error``, ``execution_error``, ``validation_error``,
    ``truncate_fields``, ``remove_fields``, ``corrupt_values``); any other
    ``effect_type`` is treated as unknown and rejected by the discriminated-union
    validator.

    Args:
        raw: JSON string mapping tool name -> list of effect specs (possibly
            empty or ``"{}"``).
        execution_id: The SSM Automation execution ID, recorded as the case
            name for per-run correlation.

    Returns:
        ``None`` if the parsed map is empty; otherwise a single ``ChaosCase``
        whose ``tool_effects`` maps each tool to its deserialised effect
        instance(s).

    Raises:
        Raises (caught upstream by the loader, never reaching the invocation
        path) on malformed JSON, a non-object top-level value, an unknown
        ``effect_type``, or any tool carrying more than one effect. Validation
        happens at SSM-read time, never mid-invocation.
    """
    parsed: Any = json.loads(raw)

    # Empty map (including "{}") is a baseline / No_Op signal, not a case.
    if not parsed:
        return None

    if not isinstance(parsed, dict):
        raise ValueError(
            "fault_injections must be a JSON object mapping tool -> effects, "
            f"got {type(parsed).__name__}"
        )

    # Deserialise each tool's effect list via the discriminated union. An unknown
    # effect_type raises here. The >1-effect-per-tool rule is enforced by the
    # ChaosCase validator below.
    tool_effects: dict[str, list[ToolEffectUnion]] = {
        tool: _EFFECT_LIST_ADAPTER.validate_python(effect_specs)
        for tool, effect_specs in parsed.items()
    }

    return ChaosCase(
        name=execution_id or None,
        input="",
        effects={"tool_effects": tool_effects},
    )


# ---------------------------------------------------------------------------
# TTL-cached, fail-closed SSM config loader
# ---------------------------------------------------------------------------
class SSMConfigLoader:
    """TTL-cached, fail-closed reader for the ``/chaos/{runtime_id}/*`` parameters.

    Holds a single cached ``RuntimeChaosConfig`` snapshot and a reusable boto3
    SSM client. ``get()`` returns the cache while it is fresh and otherwise
    refetches, always failing closed to a no-op config rather than raising
    (Requirements 1.4, 1.5, 7.1, 7.2, 8.1, 8.5).

    Attributes:
        prefix: The SSM path prefix, ``f"/chaos/{runtime_id}/"``.
        ttl: Cache time-to-live in seconds (default 10). Must be > 0.
    """

    def __init__(
        self,
        prefix: str,
        ttl: int = 10,
        ssm_client: Optional["BaseClient"] = None,
    ) -> None:
        """Initialise the loader.

        Args:
            prefix: The SSM parameter path prefix to read, ``/chaos/{runtime_id}/``.
            ttl: Cache time-to-live in seconds. Defaults to 10.
            ssm_client: Optional pre-built boto3 SSM client. When omitted, a
                client is created lazily on first fetch so that constructing the
                loader never requires AWS credentials or network access.
        """
        self.prefix = prefix
        self.ttl = ttl
        self._ssm = ssm_client
        self._cached: Optional[RuntimeChaosConfig] = None

    @property
    def ssm(self) -> "BaseClient":
        """Return the boto3 SSM client, creating it lazily on first use."""
        if self._ssm is None:
            import boto3

            self._ssm = boto3.client("ssm")
        return self._ssm

    def get(self) -> RuntimeChaosConfig:
        """Return the current chaos config, fetching from SSM only when stale.

        Returns:
            The cached config when fresh; otherwise a freshly fetched config.
            On any SSM error or invalid value, a cached no-op config
            (``active=false``, no case). Never raises to the caller.
        """
        now = time.monotonic()

        # Cache hit: fresh config, no SSM call (Requirement 1.4).
        if self._cached is not None and (now - self._cached.fetched_at) < self.ttl:
            return self._cached

        # Cache miss / expiry: fetch from SSM (Requirement 1.5).
        try:
            resp = self.ssm.get_parameters_by_path(Path=self.prefix)
            params = {
                p["Name"].rsplit("/", 1)[-1]: p["Value"]
                for p in resp.get("Parameters", [])
            }
        except Exception:
            # Fail closed on any SSM read failure (Requirement 7.1).
            logger.warning("ssm_read_failed for prefix %s", self.prefix, exc_info=True)
            self._cached = RuntimeChaosConfig.no_op(fetched_at=now)
            return self._cached

        # Parse and validate the fetched parameters.
        try:
            cfg = self._build_config(params, now)
        except Exception as exc:
            # Fail closed on any malformed/out-of-range value (Requirements 7.2, 8.5).
            logger.warning("ssm_config_invalid for prefix %s: %s", self.prefix, exc)
            cfg = RuntimeChaosConfig.no_op(fetched_at=now)

        self._cached = cfg
        return cfg

    def _build_config(
        self, params: dict[str, Any], fetched_at: float
    ) -> RuntimeChaosConfig:
        """Build a ``RuntimeChaosConfig`` from raw parameter values.

        Raises on any invalid value so the caller can fail closed: an
        out-of-range or non-numeric ``fault_rate``, or malformed
        ``fault_injections`` (propagated from ``build_chaos_case``).
        """
        # `active` parses case-insensitively to bool; absent/anything-but-true
        # is false (Requirement 1.2).
        active = params.get("active", "false").strip().lower() == "true"

        # `fault_rate` parses to float; reject values outside [0.0, 1.0]
        # (Requirement 8.5). A non-numeric value raises ValueError here.
        fault_rate = float(params.get("fault_rate", "0.0"))
        if not (0.0 <= fault_rate <= 1.0):
            raise ValueError(f"fault_rate out of range [0.0, 1.0]: {fault_rate}")

        execution_id = params.get("execution_id", "")

        # `fault_injections` -> a validated ChaosCase (or None for an empty map).
        # Malformed JSON / unknown effect_type / >1 effect per tool raises here.
        case = build_chaos_case(params.get("fault_injections", "{}"), execution_id)

        return RuntimeChaosConfig(
            active=active,
            fault_rate=fault_rate,
            case=case,
            execution_id=execution_id,
            fetched_at=fetched_at,
        )


# ---------------------------------------------------------------------------
# Runtime chaos controller (Strands plugin)
# ---------------------------------------------------------------------------
class RuntimeChaosController(Plugin):
    """Strands plugin that drives per-invocation fault injection from SSM config.

    On each ``BeforeInvocationEvent`` it reads the TTL-cached chaos config and,
    if chaos is active and the invocation is selected by ``fault_rate`` sampling,
    arms the ``_current_chaos_case`` ContextVar with the configured case so the
    reused ``ChaosPlugin`` injects the configured tool-level faults. On the
    matching ``AfterInvocationEvent`` it resets the ContextVar.

    Behaviour (Requirements 1.2, 1.3, 3.4, 3.5, 7.3, 7.4, 7.5, 8.2-8.4):
    no-op when inactive or no case armed; ``random() < fault_rate`` sampling
    (r=0 never selects, r=1 always selects); fail-closed hook bodies that never
    propagate exceptions to the caller.

    Attributes:
        name: Stable plugin identifier, ``"runtime-chaos-controller"``.
        loader: The TTL-cached, fail-closed SSM config loader.
    """

    name = "runtime-chaos-controller"

    def __init__(
        self,
        runtime_id: Optional[str] = None,
        ttl_seconds: int = 10,
    ) -> None:
        """Initialise the controller.

        Args:
            runtime_id: The AgentCore runtime ID used to scope the
                ``/chaos/{runtime_id}/`` SSM subtree. When ``None`` it is
                resolved via :func:`resolve_runtime_id` (which fails closed by
                raising ``RuntimeError`` if no source resolves).
            ttl_seconds: Cache time-to-live for the SSM loader, in seconds.
                Defaults to 10.
        """
        super().__init__()
        if runtime_id is None:
            runtime_id = resolve_runtime_id()
        self.runtime_id = runtime_id
        self.loader = SSMConfigLoader(f"/chaos/{runtime_id}/", ttl=ttl_seconds)
        # Reset tokens for armed invocations, keyed by id(event) so the matching
        # AfterInvocationEvent resets exactly the ContextVar set by its before.
        self._tokens: dict[int, Token] = {}

    @hook  # type: ignore[call-overload]
    def on_before_invocation(self, event: BeforeInvocationEvent) -> None:
        """Arm chaos for this invocation when active and selected by sampling.

        No-op when chaos is inactive or no case is armed. Otherwise samples
        ``random() < fault_rate`` and, on selection, sets the
        ``_current_chaos_case`` ContextVar, tracks the reset token by
        ``id(event)``, stamps the invocation state, and logs activation.

        Never raises out of the hook (Requirement 7.3): any exception is caught
        and the invocation proceeds with no chaos ContextVar set.
        """
        try:
            cfg = self.loader.get()

            # Dormant: chaos inactive or no case armed (Requirements 1.2, 3.5).
            if not cfg.active or cfg.case is None:
                return

            # Per-invocation sampling: P(select) == fault_rate. Using strict "<"
            # means r=0 never selects (random() in [0,1) is never < 0) and r=1
            # always selects (random() is always < 1) (Requirements 1.3, 8.2-8.4).
            if random.random() < cfg.fault_rate:
                token = _current_chaos_case.set(cfg.case)
                self._tokens[id(event)] = token
                event.invocation_state["chaos_execution_id"] = cfg.execution_id
                event.invocation_state["chaos_active"] = True
                logger.info(
                    "activated chaos execution=<%s> tools=<%s>",
                    cfg.execution_id,
                    list(cfg.case.tool_effects.keys()),
                )
        except Exception:
            # Fail closed: a controller failure must never break request handling
            # (Requirement 7.3). The invocation proceeds without chaos armed.
            logger.warning("on_before_invocation failed; skipping chaos", exc_info=True)

    @hook  # type: ignore[call-overload]
    def on_after_invocation(self, event: AfterInvocationEvent) -> None:
        """Reset the chaos ContextVar armed for the matching invocation.

        Resets the ContextVar using the token stored for ``id(event)`` so chaos
        state never leaks into a subsequent invocation (Requirement 7.4). If no
        token was stored (the invocation was never armed), this is a no-op
        (Requirement 7.5).

        Never raises out of the hook (Requirement 7.3).
        """
        try:
            token = self._tokens.pop(id(event), None)
            if token is None:
                # This invocation never armed the ContextVar (Requirement 7.5).
                return
            _current_chaos_case.reset(token)
        except Exception:
            logger.warning("on_after_invocation failed", exc_info=True)


# ---------------------------------------------------------------------------
# One-line integration facade
# ---------------------------------------------------------------------------
def chaos_plugins() -> list[Plugin]:
    """Return the chaos plugin pair for one-line agent integration.

    Returns the ``RuntimeChaosController`` (which reads SSM config and arms the
    chaos ContextVar per invocation) paired with the reused, unmodified
    ``strands_evals.chaos.ChaosPlugin`` (which performs the actual tool-level
    fault injection). Ordering matters: the controller arms the case on
    ``BeforeInvocationEvent`` before the plugin reads it on tool-call events.

    Inclusion of these plugins in a build is the coarse "chaos is loaded" intent;
    SSM Parameter Store is the fine per-invocation switch. Every invocation is a
    no-op until SSM reports ``active=true`` (Requirement 6.1).

    Note:
        ``RuntimeChaosController()`` resolves the runtime ID at construction via
        :func:`resolve_runtime_id`, which fails closed by raising ``RuntimeError``
        if no resolution source is present in the environment.

    Returns:
        ``[RuntimeChaosController(), ChaosPlugin()]``.
    """
    return [RuntimeChaosController(), ChaosPlugin()]


__all__ = [
    "chaos_plugins",
    "RuntimeChaosController",
    "RuntimeChaosConfig",
    "resolve_runtime_id",
    "build_chaos_case",
    "SSMConfigLoader",
]
