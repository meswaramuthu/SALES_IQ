"""AURA Orchestrator — Intent Classifier.

Classifies an incoming user message into one of the AURA routing intents.

Classification uses a two-stage approach:
  1. **Fast rule-based pass** — O(1) keyword matching against curated trigger
     word lists. Covers ~90% of sales requests instantly.
  2. **LLM fallback** — If the rule pass returns `unknown` AND the message is
     longer than MIN_LLM_CHARS, a lightweight LLM call resolves ambiguous
     multi-intent messages (e.g. "research Acme and book a demo").

The classifier is stateless and thread-safe — one module-level instance is
shared across all concurrent sessions.

Intent enum values map exactly to sub-agent keys in tools_config.json.
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

MIN_LLM_CHARS = 40   # Only invoke LLM fallback for longer / ambiguous messages


# ---------------------------------------------------------------------------
# Intent Enum
# ---------------------------------------------------------------------------

class Intent(str, Enum):
    DISCOVERY      = "discovery_agent"
    QUALIFICATION  = "qualification_agent"
    BOOKING        = "booking_agent"
    PROPOSAL       = "proposal_agent"
    FOLLOWUP       = "followup_agent"
    REVENUE        = "revenue_agent"
    DEALDESK       = "dealdesk_agent"
    UNKNOWN        = "unknown"

    def agent_key(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Trigger word banks — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

_RULES: list[tuple[Intent, list[str]]] = [
    # Deal Desk — must come before PROPOSAL to avoid "discount proposal" misrouting
    (Intent.DEALDESK, [
        "deal desk", "dealdesk", "deal-desk",
        "approve deal", "approval request", "approve discount",
        "discount request", "pricing exception", "pricing approval",
        "custom terms", "non-standard terms", "term negotiation",
        "legal review", "contract review", "nda", "multi-year deal",
        "multi year deal", "enterprise deal", "exception",
    ]),

    # Discovery
    (Intent.DISCOVERY, [
        "find leads", "find prospects", "find contacts",
        "research prospect", "research company", "research account",
        "icp score", "icp scoring", "ideal customer",
        "company intel", "firmographic", "technographic",
        "market mapping", "tam", "target accounts", "lookalike",
        "enrich", "enrichment", "apollo", "clearbit",
        "prospect list", "lead list", "generate leads",
    ]),

    # Qualification
    (Intent.QUALIFICATION, [
        "qualify", "qualified", "qualification",
        "bant", "meddic", "meddicc",
        "is this a good fit", "good fit", "worth pursuing",
        "decision maker", "decision-maker", "economic buyer",
        "champion", "stakeholder map", "stakeholder mapping",
        "pain point", "pain points",
        "competitor analysis", "competitive positioning",
        "budget", "authority", "need", "timeline",
        "next best action", "next action",
    ]),

    # Booking
    (Intent.BOOKING, [
        "schedule", "book", "booking",
        "set up a meeting", "set up a call", "arrange a call",
        "calendar", "availability", "free slot", "time slot",
        "demo call", "discovery call", "kick-off call", "qbr",
        "send invite", "calendar invite",
        "reschedule", "cancel meeting",
        "meeting brief", "prep brief", "meeting prep",
        "google meet", "video call",
    ]),

    # Proposal
    (Intent.PROPOSAL, [
        "proposal", "quote", "pricing quote",
        "pitch deck", "deck", "one-pager",
        "statement of work", "sow",
        "business case", "roi", "return on investment",
        "value proposition", "pricing",
        "generate proposal", "write a proposal", "draft proposal",
        "docusign", "e-signature", "send for signature",
        "contract draft",
    ]),

    # Follow-up
    (Intent.FOLLOWUP, [
        "follow up", "follow-up", "followup",
        "no response", "not replied", "ghosted", "no reply",
        "re-engage", "re-engagement", "win back",
        "nurture", "drip", "sequence", "cadence",
        "outreach sequence", "email sequence",
        "post-meeting recap", "meeting recap", "meeting notes",
        "reminder",
    ]),

    # Revenue / Pipeline
    (Intent.REVENUE, [
        "pipeline", "revenue", "forecast", "forecasting",
        "arr", "mrr", "annual recurring", "monthly recurring",
        "quota", "attainment", "quota attainment",
        "win rate", "conversion rate", "funnel",
        "deal velocity", "sales velocity",
        "at risk", "at-risk deals", "stale deals",
        "leaderboard", "rep performance",
        "cohort", "this quarter", "next quarter",
        "weekly report", "monthly report", "pipeline report",
        "churn", "expansion revenue",
    ]),
]


def _keyword_match(text: str) -> Optional[Intent]:
    """Return the first matching intent, or None if no match."""
    lower = text.lower()
    for intent, keywords in _RULES:
        for kw in keywords:
            # Match whole-word or phrase (avoids "quote" matching "unquote")
            pattern = r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])"
            if re.search(pattern, lower):
                logger.debug("Intent matched by keyword '%s' → %s", kw, intent.name)
                return intent
    return None


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are an intent classifier for a B2B sales AI assistant called AURA.
Classify the user's message into EXACTLY ONE of these intents:
  discovery_agent      — prospect research, ICP scoring, lead lists, company intel
  qualification_agent  — BANT/MEDDIC scoring, deal qualification, stakeholder mapping
  booking_agent        — meeting scheduling, calendar, demo booking, meeting prep
  proposal_agent       — proposal/quote generation, pricing, ROI, DocuSign
  followup_agent       — follow-up emails, sequences, post-meeting recaps, re-engagement
  revenue_agent        — pipeline analytics, forecasting, quota, win rate, deal velocity
  dealdesk_agent       — discount approvals, custom terms, contract review, deal structure
  unknown              — cannot determine intent with confidence

Respond with ONLY the intent name (e.g. "booking_agent"). No explanation."""


def _llm_classify(user_message: str) -> Intent:
    """Use a fast Gemini Flash call to classify ambiguous messages."""
    try:
        import google.generativeai as genai  # type: ignore

        model = genai.GenerativeModel("gemini-2.0-flash-lite")
        resp = model.generate_content(
            [
                {"role": "model", "parts": [_LLM_SYSTEM_PROMPT]},
                {"role": "user", "parts": [user_message]},
            ],
            generation_config={"temperature": 0.0, "max_output_tokens": 32},
        )
        raw = resp.text.strip().lower().rstrip(".")
        for intent in Intent:
            if intent.value == raw or intent.name.lower() == raw:
                logger.debug("LLM intent classification: '%s' → %s", raw, intent.name)
                return intent
    except Exception as exc:
        logger.warning("LLM intent classification failed: %s", exc)
    return Intent.UNKNOWN


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------

class IntentClassifier:
    """Stateless, thread-safe intent classifier.

    Usage::
        clf = IntentClassifier()
        intent = clf.classify("Book a demo with Acme Corp next Tuesday")
        # intent → Intent.BOOKING
    """

    def classify(self, user_message: str, use_llm_fallback: bool = True) -> Intent:
        """Classify a user message into an Intent.

        Args:
            user_message:     The raw user turn text.
            use_llm_fallback: If True and keyword match fails, invoke LLM.

        Returns:
            An Intent enum value.
        """
        if not user_message or not user_message.strip():
            return Intent.UNKNOWN

        # Stage 1 — fast keyword match
        intent = _keyword_match(user_message)
        if intent is not None:
            return intent

        # Stage 2 — LLM fallback for longer / ambiguous messages
        if use_llm_fallback and len(user_message.strip()) >= MIN_LLM_CHARS:
            return _llm_classify(user_message)

        return Intent.UNKNOWN

    def classify_multi(self, user_message: str) -> list[Intent]:
        """Detect multiple intents in a single message (for compound requests).

        Returns a list of unique intents, in order of detection.
        Used for messages like "research Acme and then book a demo with them".
        """
        lower = user_message.lower()
        seen: set[Intent] = set()
        ordered: list[Intent] = []
        for intent, keywords in _RULES:
            for kw in keywords:
                pattern = r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])"
                if re.search(pattern, lower) and intent not in seen:
                    seen.add(intent)
                    ordered.append(intent)
                    break
        return ordered or [Intent.UNKNOWN]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_classifier: Optional[IntentClassifier] = None


def get_classifier() -> IntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier
