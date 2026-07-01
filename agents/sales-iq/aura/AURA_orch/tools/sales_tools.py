"""AURA Orchestrator — Sales Session Tools.

These are ADK-registered tool functions exposed to the orchestrator agent.
The agent can call these to read / write structured sales state in Firestore,
inspect session context, and trigger routing to sub-agents programmatically.

Every function that touches session state accepts `tool_context` (injected
automatically by ADK) so it can extract user_id / session_id without the
agent having to pass them explicitly.

Tools exposed:
  get_session_context      — Return formatted session context for the agent
  store_lead               — Upsert a lead into the session
  store_opportunity        — Upsert an opportunity/deal into the session
  store_meeting            — Upsert a meeting record into the session
  store_proposal           — Upsert a proposal record into the session
  update_qualification     — Write BANT/MEDDIC scores for an opportunity
  set_active_opportunity   — Point the session at a specific opportunity
  get_opportunity_summary  — Return a formatted opportunity brief
  classify_intent          — Classify a message and return the target agent name
  get_all_leads            — List all leads in the current session
  get_all_meetings         — List all meetings (optionally filter by status)
  get_all_proposals        — List all proposals (optionally filter by status)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from AURA_orch.intent.classifier import Intent, get_classifier
from AURA_orch.session.models import (
    LeadData,
    MeetingRecord,
    OpportunityState,
    ProposalRecord,
    QualificationStatus,
    BANTScore,
    MEDDICScore,
)
from AURA_orch.session.session_manager import get_session_manager, SessionManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mgr() -> SessionManager:
    return get_session_manager()


def _ids(tool_context: dict[str, Any]) -> tuple[str, str]:
    return SessionManager.extract_ids(tool_context)


# ---------------------------------------------------------------------------
# Context / read tools
# ---------------------------------------------------------------------------

def get_session_context(tool_context: dict[str, Any]) -> str:
    """Return a formatted summary of the current session state.

    Call this at the start of every orchestrator response to inject
    up-to-date deal, lead, meeting, and proposal context.

    Returns:
        A markdown-formatted context block ready to include in the response.
    """
    user_id, session_id = _ids(tool_context)
    return _mgr().get_context_summary(user_id, session_id)


def get_opportunity_summary(
    opportunity_id: str,
    tool_context: dict[str, Any],
) -> str:
    """Return a detailed formatted summary of a single opportunity.

    Args:
        opportunity_id: The opportunity ID from the session.
        tool_context:   Injected by ADK.

    Returns:
        A formatted deal brief, or a message if the opportunity is not found.
    """
    user_id, session_id = _ids(tool_context)
    session = _mgr().get_session(user_id, session_id)
    opp = session.get_opportunity(opportunity_id)
    if not opp:
        return f"No opportunity found with ID: {opportunity_id}"

    q = opp.qualification
    lines = [
        f"# Deal Brief — {opp.deal_name}",
        f"**Company:** {opp.company_name} ({opp.company_domain})",
        f"**Stage:** {opp.stage} | **Amount:** ${opp.amount:,.0f} | **Close Date:** {opp.close_date}",
        f"**Owner:** {opp.owner_email} | **Probability:** {opp.probability:.0f}%",
        f"**Weighted Value:** ${opp.weighted_value:,.0f}",
        f"**Days in Stage:** {opp.days_in_stage} | **Last Activity:** {opp.last_activity_date}",
        "",
        f"### Qualification",
        f"BANT: {q.bant.total}/20 ({q.bant.verdict}) | MEDDIC: {q.meddic.total}/30 ({q.meddic.verdict})",
    ]
    if q.primary_pain_points:
        lines.append(f"**Pain Points:** {', '.join(q.primary_pain_points)}")
    if q.recommended_next_action:
        lines.append(f"**Next Action:** {q.recommended_next_action}")
    if opp.at_risk:
        lines.append(f"⚠️ **AT RISK:** {opp.at_risk_reason}")
    return "\n".join(lines)


def get_all_leads(tool_context: dict[str, Any]) -> str:
    """Return a formatted list of all leads stored in the current session.

    Returns:
        JSON-formatted list of leads (id, name, company, icp_score, tier).
    """
    user_id, session_id = _ids(tool_context)
    session = _mgr().get_session(user_id, session_id)
    leads = []
    for raw in session.leads.values():
        try:
            lead = LeadData.model_validate(raw)
            leads.append({
                "lead_id": lead.lead_id,
                "name": f"{lead.first_name} {lead.last_name}".strip(),
                "title": lead.title,
                "company": lead.company_name,
                "email": lead.email,
                "icp_score": lead.icp_score,
                "icp_tier": lead.icp_tier,
                "crm_contact_id": lead.crm_contact_id,
            })
        except Exception:
            pass
    return json.dumps({"total": len(leads), "leads": leads}, indent=2)


def get_all_meetings(
    status_filter: str,
    tool_context: dict[str, Any],
) -> str:
    """Return all meetings in the session, optionally filtered by status.

    Args:
        status_filter: One of "all", "scheduled", "completed", "cancelled".
        tool_context:  Injected by ADK.

    Returns:
        JSON-formatted list of meetings.
    """
    user_id, session_id = _ids(tool_context)
    session = _mgr().get_session(user_id, session_id)
    meetings = []
    for raw in session.meetings.values():
        try:
            m = MeetingRecord.model_validate(raw)
            if status_filter not in ("all", "") and m.status != status_filter:
                continue
            meetings.append({
                "meeting_id": m.meeting_id,
                "title": m.title,
                "type": m.meeting_type,
                "start_time": m.start_time,
                "status": m.status,
                "meet_link": m.meet_link,
                "opportunity_id": m.opportunity_id,
            })
        except Exception:
            pass
    meetings.sort(key=lambda x: x["start_time"])
    return json.dumps({"total": len(meetings), "meetings": meetings}, indent=2)


def get_all_proposals(
    status_filter: str,
    tool_context: dict[str, Any],
) -> str:
    """Return all proposals in the session, optionally filtered by status.

    Args:
        status_filter: One of "all", "draft", "sent", "signed", "rejected".
        tool_context:  Injected by ADK.

    Returns:
        JSON-formatted list of proposals.
    """
    user_id, session_id = _ids(tool_context)
    session = _mgr().get_session(user_id, session_id)
    proposals = []
    for raw in session.proposals.values():
        try:
            p = ProposalRecord.model_validate(raw)
            if status_filter not in ("all", "") and p.status != status_filter:
                continue
            proposals.append({
                "proposal_id": p.proposal_id,
                "title": p.title,
                "company": p.prospect_company,
                "amount": p.proposed_price_annual,
                "status": p.status,
                "docusign_status": p.docusign_status,
                "gdrive_doc_url": p.gdrive_doc_url,
            })
        except Exception:
            pass
    return json.dumps({"total": len(proposals), "proposals": proposals}, indent=2)


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------

def store_lead(
    lead_data_json: str,
    tool_context: dict[str, Any],
) -> str:
    """Upsert a lead record into the current session.

    Args:
        lead_data_json: JSON string matching the LeadData schema. Required fields:
            first_name, last_name, company_name. All others optional.
        tool_context:   Injected by ADK.

    Returns:
        Confirmation message with the lead_id.
    """
    user_id, session_id = _ids(tool_context)
    try:
        raw = json.loads(lead_data_json)
        lead = LeadData.model_validate(raw)
        _mgr().upsert_lead(user_id, session_id, lead)
        return (
            f"Lead stored: {lead.first_name} {lead.last_name} @ {lead.company_name} "
            f"(lead_id={lead.lead_id}, ICP={lead.icp_score:.1f}/10)"
        )
    except Exception as exc:
        logger.error("store_lead failed: %s", exc)
        return f"Error storing lead: {exc}"


def store_opportunity(
    opportunity_data_json: str,
    tool_context: dict[str, Any],
) -> str:
    """Upsert a deal/opportunity into the current session.

    Args:
        opportunity_data_json: JSON string matching the OpportunityState schema.
            Required: deal_name, company_name. All others optional.
        tool_context:          Injected by ADK.

    Returns:
        Confirmation message with opportunity_id.
    """
    user_id, session_id = _ids(tool_context)
    try:
        raw = json.loads(opportunity_data_json)
        opp = OpportunityState.model_validate(raw)
        _mgr().upsert_opportunity(user_id, session_id, opp)
        return (
            f"Opportunity stored: {opp.deal_name} — {opp.company_name} "
            f"| Stage: {opp.stage} | Value: ${opp.amount:,.0f} "
            f"(opportunity_id={opp.opportunity_id})"
        )
    except Exception as exc:
        logger.error("store_opportunity failed: %s", exc)
        return f"Error storing opportunity: {exc}"


def store_meeting(
    meeting_data_json: str,
    tool_context: dict[str, Any],
) -> str:
    """Upsert a meeting record into the current session.

    Args:
        meeting_data_json: JSON string matching the MeetingRecord schema.
            Required: title, start_time. All others optional.
        tool_context:      Injected by ADK.

    Returns:
        Confirmation message with meeting_id.
    """
    user_id, session_id = _ids(tool_context)
    try:
        raw = json.loads(meeting_data_json)
        meeting = MeetingRecord.model_validate(raw)
        _mgr().upsert_meeting(user_id, session_id, meeting)
        return (
            f"Meeting stored: {meeting.title} — {meeting.start_time} "
            f"| Status: {meeting.status} (meeting_id={meeting.meeting_id})"
        )
    except Exception as exc:
        logger.error("store_meeting failed: %s", exc)
        return f"Error storing meeting: {exc}"


def store_proposal(
    proposal_data_json: str,
    tool_context: dict[str, Any],
) -> str:
    """Upsert a proposal record into the current session.

    Args:
        proposal_data_json: JSON string matching the ProposalRecord schema.
            Required: title, prospect_company. All others optional.
        tool_context:       Injected by ADK.

    Returns:
        Confirmation message with proposal_id.
    """
    user_id, session_id = _ids(tool_context)
    try:
        raw = json.loads(proposal_data_json)
        proposal = ProposalRecord.model_validate(raw)
        _mgr().upsert_proposal(user_id, session_id, proposal)
        return (
            f"Proposal stored: {proposal.title} — {proposal.prospect_company} "
            f"| ${proposal.proposed_price_annual:,.0f}/yr | Status: {proposal.status} "
            f"(proposal_id={proposal.proposal_id})"
        )
    except Exception as exc:
        logger.error("store_proposal failed: %s", exc)
        return f"Error storing proposal: {exc}"


def update_qualification(
    opportunity_id: str,
    qualification_json: str,
    tool_context: dict[str, Any],
) -> str:
    """Write BANT/MEDDIC qualification scores for an opportunity.

    Args:
        opportunity_id:    The opportunity to update.
        qualification_json: JSON matching QualificationStatus schema.
            Key fields: bant (dict), meddic (dict), stakeholder_map (list),
            primary_pain_points (list), recommended_next_action (str).
        tool_context:      Injected by ADK.

    Returns:
        Summary of recorded qualification scores.
    """
    user_id, session_id = _ids(tool_context)
    try:
        raw = json.loads(qualification_json)
        qual = QualificationStatus.model_validate({**raw, "opportunity_id": opportunity_id})
        _mgr().update_qualification(user_id, session_id, opportunity_id, qual)
        return (
            f"Qualification updated for opportunity {opportunity_id}: "
            f"BANT={qual.bant.total}/20 ({qual.bant.verdict}), "
            f"MEDDIC={qual.meddic.total}/30 ({qual.meddic.verdict}). "
            f"Next action: {qual.recommended_next_action}"
        )
    except Exception as exc:
        logger.error("update_qualification failed: %s", exc)
        return f"Error updating qualification: {exc}"


def set_active_opportunity(
    opportunity_id: str,
    tool_context: dict[str, Any],
) -> str:
    """Set the currently focused opportunity in the session.

    Call this whenever the user switches context to a different deal.
    The active opportunity ID is injected into every subsequent context summary.

    Args:
        opportunity_id: The opportunity_id to make active.
        tool_context:   Injected by ADK.

    Returns:
        Confirmation string.
    """
    user_id, session_id = _ids(tool_context)
    session = _mgr().get_session(user_id, session_id)
    opp = session.get_opportunity(opportunity_id)
    session.active_opportunity_id = opportunity_id
    _mgr().save_session(session)
    if opp:
        return f"Active opportunity set: {opp.deal_name} — {opp.company_name} (ID: {opportunity_id})"
    return f"Active opportunity set to ID: {opportunity_id} (not yet in session — load from CRM first)"


# ---------------------------------------------------------------------------
# Intent tool
# ---------------------------------------------------------------------------

def classify_intent(
    user_message: str,
    tool_context: dict[str, Any],  # noqa: ARG001 — unused but required by ADK signature
) -> str:
    """Classify a sales message and return the target sub-agent name.

    Use this when the orchestrator needs to explicitly verify routing
    before delegating. Not needed for most flows (ADK routes automatically).

    Args:
        user_message: The user turn text to classify.
        tool_context: Injected by ADK.

    Returns:
        JSON with keys: intent (agent name), confidence (high|low|unknown).
    """
    clf = get_classifier()
    intents = clf.classify_multi(user_message)
    primary = intents[0] if intents else Intent.UNKNOWN
    return json.dumps({
        "primary_intent": primary.value,
        "all_intents": [i.value for i in intents],
        "confidence": "high" if primary != Intent.UNKNOWN else "low",
    })


# ---------------------------------------------------------------------------
# Tool list for ADK registration
# ---------------------------------------------------------------------------

SALES_TOOLS = [
    get_session_context,
    get_opportunity_summary,
    get_all_leads,
    get_all_meetings,
    get_all_proposals,
    store_lead,
    store_opportunity,
    store_meeting,
    store_proposal,
    update_qualification,
    set_active_opportunity,
    classify_intent,
]
