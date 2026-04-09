"""
Copilot usage tracking module.

Listens to SDK session events, normalises them into a stable internal schema,
and emits clean usage snapshots to the rest of the application.

Design principles:
- Provider-specific logic is isolated here; the rest of the app never touches
  raw Copilot SDK event details.
- All values sourced from the SDK are labelled with a confidence field
  (authoritative / estimated / unavailable).
- No hard-coded plan allowances, model multipliers, or token billing rules.
- Idempotent: duplicate events for the same api_call_id are ignored.
- Gracefully degrades when fields are missing or events are partial.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from copilot.generated.session_events import (
    SessionEvent,
    SessionEventType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal schema
# ---------------------------------------------------------------------------

@dataclass
class TurnUsage:
    """Per-turn usage snapshot for a single user prompt → assistant reply."""

    turn_id: str = ""
    model: str = ""
    model_multiplier: float | None = None
    premium_requests: float = 0
    input_tokens: float = 0
    output_tokens: float = 0
    cache_read_tokens: float = 0
    cache_write_tokens: float = 0
    total_nano_aiu: float = 0
    duration_ms: float = 0
    # IDs of assistant.usage events already accounted for (idempotency guard).
    _seen_api_call_ids: set = field(default_factory=set, repr=False)

    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "model": self.model,
            "model_multiplier": self.model_multiplier,
            "premium_requests": self.premium_requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_nano_aiu": self.total_nano_aiu,
            "duration_ms": self.duration_ms,
        }


@dataclass
class SessionUsage:
    """Cumulative session-level usage totals."""

    total_premium_requests: float = 0
    total_input_tokens: float = 0
    total_output_tokens: float = 0
    total_cache_read_tokens: float = 0
    total_cache_write_tokens: float = 0
    total_nano_aiu: float = 0
    total_duration_ms: float = 0
    # Context window tracking (from session.context_changed).
    current_context_tokens: float | None = None
    context_token_limit: float | None = None

    def to_dict(self) -> dict:
        return {
            "total_premium_requests": self.total_premium_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_write_tokens": self.total_cache_write_tokens,
            "total_nano_aiu": self.total_nano_aiu,
            "total_duration_ms": self.total_duration_ms,
            "current_context_tokens": self.current_context_tokens,
            "context_token_limit": self.context_token_limit,
        }


@dataclass
class MonthlyUsage:
    """
    Monthly premium request quota snapshot.

    Populated from QuotaSnapshot if available in the SDK's assistant.usage
    event.  Values come directly from GitHub – they are authoritative when
    present.
    """

    used_requests: float | None = None
    entitlement_requests: float | None = None
    is_unlimited: bool = False
    remaining_percentage: float | None = None
    overage: float | None = None
    reset_date: str | None = None
    confidence: str = "unavailable"  # authoritative | estimated | unavailable

    def to_dict(self) -> dict:
        return {
            "used_requests": self.used_requests,
            "entitlement_requests": self.entitlement_requests,
            "is_unlimited": self.is_unlimited,
            "remaining_percentage": self.remaining_percentage,
            "overage": self.overage,
            "reset_date": self.reset_date,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Per-chat tracker
# ---------------------------------------------------------------------------

class ChatUsageTracker:
    """
    Tracks usage for a single chat (== Copilot session).

    Attach via ``session.on(tracker.handle_event)`` before sending messages.
    Call ``start_turn()`` before each ``send_and_wait()`` and
    ``finalise_turn()`` after it returns to get a clean turn snapshot.
    """

    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.session_usage = SessionUsage()
        self.monthly_usage = MonthlyUsage()
        self._current_turn: TurnUsage | None = None
        self._finalised_turns: list[TurnUsage] = []
        # Set to True once SESSION_USAGE_INFO provides an authoritative running
        # session total.  When True, finalise_turn() does NOT add the turn's
        # premium_requests to the session total a second time (avoid double-
        # counting when both sources are active).  Reset each turn so that if
        # the SDK stops sending SESSION_USAGE_INFO we fall back to accumulation.
        self._session_total_is_authoritative: bool = False

    # -- Turn lifecycle -----------------------------------------------------

    def start_turn(self, turn_id: str = "") -> None:
        """Begin a new turn; resets the per-turn accumulator."""
        self._current_turn = TurnUsage(turn_id=turn_id)
        # Reset per-turn so that if the SDK stops emitting SESSION_USAGE_INFO
        # for a particular turn we fall back to turn-level accumulation.
        self._session_total_is_authoritative = False

    def finalise_turn(self) -> TurnUsage:
        """
        Finalise and return the current turn, folding it into session totals.

        Returns a zeroed TurnUsage if no turn was started (defensive).
        """
        turn = self._current_turn or TurnUsage()
        self._current_turn = None

        # Fold into session totals.
        # premium_requests: only accumulate from turns when the SDK has NOT
        # provided an authoritative running total via SESSION_USAGE_INFO.
        # If it has, the session total is already correct and adding the turn
        # value again would double-count.
        if not self._session_total_is_authoritative:
            self.session_usage.total_premium_requests += turn.premium_requests
        self.session_usage.total_input_tokens += turn.input_tokens
        self.session_usage.total_output_tokens += turn.output_tokens
        self.session_usage.total_cache_read_tokens += turn.cache_read_tokens
        self.session_usage.total_cache_write_tokens += turn.cache_write_tokens
        self.session_usage.total_nano_aiu += turn.total_nano_aiu
        self.session_usage.total_duration_ms += turn.duration_ms

        self._finalised_turns.append(turn)
        return turn

    # -- Event handler ------------------------------------------------------

    def handle_event(self, event: SessionEvent) -> None:
        """
        Session-event callback.  Safe to register via ``session.on()``.

        Handles:
        - assistant.usage  → per-turn token/cost accumulation + quota snapshot
        - session.context_changed → context window tracking
        - session.usage_info → additional session-level info
        """
        try:
            if event.type == SessionEventType.ASSISTANT_USAGE:
                self._on_assistant_usage(event)
            elif event.type == SessionEventType.SESSION_CONTEXT_CHANGED:
                self._on_context_changed(event)
            elif event.type == SessionEventType.SESSION_USAGE_INFO:
                self._on_session_usage_info(event)
        except Exception:
            logger.warning(
                "Usage tracker event error for chat %s", self.chat_id, exc_info=True,
            )

    # -- Private event processors -------------------------------------------

    def _on_assistant_usage(self, event: SessionEvent) -> None:
        d = event.data
        if d is None:
            return

        # Idempotency: skip duplicate events keyed by api_call_id.
        api_call_id = getattr(d, "api_call_id", None)

        turn = self._current_turn
        if turn is None:
            # Usage event arrived outside a tracked turn; log but don't crash.
            logger.debug("Usage event outside turn for chat %s", self.chat_id)
            return

        if api_call_id:
            if api_call_id in turn._seen_api_call_ids:
                logger.debug("Duplicate usage event %s ignored", api_call_id)
                return
            turn._seen_api_call_ids.add(api_call_id)

        # Token counts.
        turn.input_tokens += _safe_float(d, "input_tokens")
        turn.output_tokens += _safe_float(d, "output_tokens")
        turn.cache_read_tokens += _safe_float(d, "cache_read_tokens")
        turn.cache_write_tokens += _safe_float(d, "cache_write_tokens")
        turn.duration_ms += _safe_float(d, "duration")

        # Model & cost.
        model = getattr(d, "model", None)
        if model:
            turn.model = model
        cost = getattr(d, "cost", None)
        if cost is not None:
            turn.model_multiplier = cost
            turn.premium_requests += cost

        # Nano-AIU from CopilotUsage if present.
        copilot_usage = getattr(d, "copilot_usage", None)
        if copilot_usage is not None:
            nano = getattr(copilot_usage, "total_nano_aiu", None)
            if nano is not None:
                turn.total_nano_aiu += nano

        # Quota snapshot → monthly usage (authoritative from GitHub).
        quota_snapshots = getattr(d, "quota_snapshots", None)
        if quota_snapshots:
            self._update_monthly_from_quota(quota_snapshots)

    def _on_context_changed(self, event: SessionEvent) -> None:
        d = event.data
        if d is None:
            return
        current = getattr(d, "current_tokens", None)
        limit = getattr(d, "token_limit", None)
        if current is not None:
            self.session_usage.current_context_tokens = current
        if limit is not None:
            self.session_usage.context_token_limit = limit

    def _on_session_usage_info(self, event: SessionEvent) -> None:
        d = event.data
        if d is None:
            return
        # SESSION_USAGE_INFO carries a running total of premium requests for
        # the whole Copilot session (authoritative from GitHub's billing layer).
        # Mark the flag so finalise_turn() knows not to add the turn's
        # premium_requests on top of this.
        total_pr = getattr(d, "total_premium_requests", None)
        if total_pr is not None:
            self._session_total_is_authoritative = True
            self.session_usage.total_premium_requests = total_pr

    def _update_monthly_from_quota(self, snapshots: dict) -> None:
        """
        Select the most relevant quota snapshot entry for premium request tracking.

        The SDK sends multiple quota keys (e.g. "completions", "chat",
        "premium_requests").  The "completions" / "chat" entries are typically
        unlimited for all plans; the "premium_requests" entry carries the
        bounded monthly allowance that we actually want to display.

        Selection priority:
          1. Any key whose name contains "premium" (case-insensitive).
          2. Any key where is_unlimited_entitlement = False (bounded quota).
          3. Fall back to the first entry if all are unlimited or only one exists.
        """
        if not snapshots:
            return

        best_key: str | None = None
        best_snap = None
        fallback_key: str | None = None
        fallback_snap = None

        for key, snap in snapshots.items():
            is_unlimited = getattr(snap, "is_unlimited_entitlement", False)
            logger.debug(
                "Quota snapshot key=%r unlimited=%s used=%s entitlement=%s remaining_pct=%s",
                key, is_unlimited,
                getattr(snap, "used_requests", None),
                getattr(snap, "entitlement_requests", None),
                getattr(snap, "remaining_percentage", None),
            )

            # Keep the very first entry as a last-resort fallback.
            if fallback_snap is None:
                fallback_key, fallback_snap = key, snap

            # Highest priority: explicit "premium" key.
            if "premium" in key.lower():
                best_key, best_snap = key, snap
                break

            # Second priority: any bounded (non-unlimited) quota.
            if not is_unlimited and best_snap is None:
                best_key, best_snap = key, snap

        chosen_key = best_key if best_snap is not None else fallback_key
        chosen_snap = best_snap if best_snap is not None else fallback_snap

        if chosen_snap is None:
            return

        logger.info(
            "Monthly quota from snapshot key=%r: used=%s / %s unlimited=%s",
            chosen_key,
            getattr(chosen_snap, "used_requests", None),
            getattr(chosen_snap, "entitlement_requests", None),
            getattr(chosen_snap, "is_unlimited_entitlement", False),
        )

        self.monthly_usage.used_requests = getattr(chosen_snap, "used_requests", None)
        self.monthly_usage.entitlement_requests = getattr(chosen_snap, "entitlement_requests", None)
        self.monthly_usage.is_unlimited = getattr(chosen_snap, "is_unlimited_entitlement", False)
        # Normalise remaining_percentage to the 0–1 scale expected by the
        # frontend formula ``(1 - remaining) * 100``.  The SDK may return a
        # 0-100 value (e.g. 73.0 meaning 73 % remaining), which would produce
        # absurd results like -7200 % without normalisation.
        remaining = getattr(chosen_snap, "remaining_percentage", None)
        if remaining is not None and remaining > 1.0:
            remaining = remaining / 100.0
        self.monthly_usage.remaining_percentage = remaining
        self.monthly_usage.overage = getattr(chosen_snap, "overage", None)
        reset = getattr(chosen_snap, "reset_date", None)
        if reset is not None:
            self.monthly_usage.reset_date = (
                reset.isoformat() if isinstance(reset, datetime) else str(reset)
            )
        self.monthly_usage.confidence = "authoritative"

    # -- Snapshot for API response ------------------------------------------

    def snapshot(self, turn: TurnUsage | None = None) -> dict:
        """
        Return a complete usage snapshot suitable for sending to the frontend.

        If *turn* is provided its data is included; otherwise the in-progress
        turn (if any) is snapshotted.
        """
        t = turn or self._current_turn
        return {
            "turn": t.to_dict() if t else None,
            "session": self.session_usage.to_dict(),
            "monthly": self.monthly_usage.to_dict(),
        }


# ---------------------------------------------------------------------------
# Registry – maps chat_id to its tracker
# ---------------------------------------------------------------------------

_trackers: dict[str, ChatUsageTracker] = {}


def get_or_create_tracker(chat_id: str) -> ChatUsageTracker:
    """Return (or create) the usage tracker for a chat."""
    if chat_id not in _trackers:
        _trackers[chat_id] = ChatUsageTracker(chat_id)
    return _trackers[chat_id]


def discard_tracker(chat_id: str) -> None:
    """Remove the tracker for a chat (when the session is destroyed)."""
    _trackers.pop(chat_id, None)


def get_tracker(chat_id: str) -> ChatUsageTracker | None:
    """Return the tracker for a chat, or None."""
    return _trackers.get(chat_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(obj: Any, attr: str) -> float:
    """Read a float attribute defensively, returning 0 if missing/None."""
    val = getattr(obj, attr, None)
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
