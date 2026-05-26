"""Input guardrail node — first gate in the LangGraph pipeline.

Runs three checks in sequence:
  1. Deterministic input validation (length, charset)  — fast, no LLM
  2. PII detection                                      — logs types, never blocks alone
  3. LLM-based safety + topic relevance + injection     — fail-open on LLM errors
"""

import logging

from src.state import TripPlannerState
from src.guardrails import deterministic_guardrails, input_guardrails, pii_handler

logger = logging.getLogger(__name__)


async def guardrail_node(state: TripPlannerState) -> dict:
    raw_input = state.get("raw_input", "")
    errors: list[str] = []

    # ── Step 1: Deterministic checks (no LLM) ────────────────────────────────
    det = deterministic_guardrails.validate_raw_input(raw_input)
    if not det.passed:
        return {
            "guardrail_result": {
                "passed": False,
                "reason": det.reason,
                "severity": "block",
                "pii_detected": [],
                "details": det.details,
            },
            "errors": [f"guardrail (deterministic): {det.reason}"],
        }

    # ── Step 2: PII detection — warn and log, but never block on presence alone ──
    pii_entities = pii_handler.detect_pii(raw_input)
    pii_types    = list({e.type for e in pii_entities})
    if pii_types:
        logger.warning(f"[guardrail] PII detected in raw_input: {pii_types}")
        errors.append(f"guardrail (pii_detected): types={pii_types}")

    # ── Step 3: LLM safety + relevance + prompt-injection check ──────────────
    safety = await input_guardrails.check(raw_input)
    if not safety.passed:
        return {
            "guardrail_result": {
                "passed": False,
                "reason": safety.reason,
                "severity": safety.severity,
                "pii_detected": pii_types,
                "details": safety.details,
            },
            "errors": errors + [f"guardrail (safety): {safety.reason}"],
        }

    final_severity = (
        "warn" if (pii_types or safety.severity == "warn") else "pass"
    )
    return {
        "guardrail_result": {
            "passed": True,
            "reason": safety.reason or "All checks passed.",
            "severity": final_severity,
            "pii_detected": pii_types,
            "details": safety.details,
        },
        "errors": errors,
    }
