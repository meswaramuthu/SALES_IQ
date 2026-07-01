"""AURA Orchestrator — Session State Models.

Defines every entity the orchestrator tracks across turns:

  LeadData            — prospect profile (contact + firmographics + ICP score)
  QualificationStatus — BANT/MEDDIC scores per opportunity
  MeetingRecord       — scheduled meetings (calendar event metadata)
  ProposalRecord      — generated proposal and DocuSign envelope state
  OpportunityState    — top-level CRM deal snapshot
  AURASession         — full session document stored in Firestore

Design principles:
  - All models are Pydantic v2 (model_validate / model_dump).
  - Every model has `updated_at` so merges can use last-writer-wins.
  - All fields have safe defaults so partial updates never fail validation.
  - `AURASession.merge()` merges a dict partial update without clobbering
    untouched fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Lead Data
# ---------------------------------------------------------------------------

class LeadData(BaseModel):
    """A single enriched prospect / lead."""

    lead_id: str = Field(default_factory=lambda: str(uuid4()))
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    title: str = ""
    seniority: str = ""                  # c_suite | vp | director | manager | ic
    linkedin_url: str = ""

    company_name: str = ""
    company_domain: str = ""
    company_industry: str = ""
    company_headcount: int = 0
    company_funding_stage: str = ""      # seed | series_a | series_b | ... | public
    company_annual_revenue: str = ""
    company_tech_stack: list[str] = Field(default_factory=list)
    company_location: str = ""

    icp_score: float = 0.0               # 0–10 weighted ICP score
    icp_tier: str = ""                   # A | B | C
    icp_breakdown: dict[str, float] = Field(default_factory=dict)  # dimension → score

    source: str = ""                     # apollo | linkedin | manual | crm
    crm_contact_id: str = ""             # HubSpot / Salesforce contact ID

    outreach_angle: str = ""             # 1-sentence personalised hook
    notes: str = ""
    updated_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Qualification Status
# ---------------------------------------------------------------------------

class BANTScore(BaseModel):
    budget: int = 0          # 1–5
    authority: int = 0
    need: int = 0
    timeline: int = 0
    total: int = 0
    verdict: str = ""        # Disqualify | Nurture | Advance


class MEDDICScore(BaseModel):
    metrics: int = 0         # 1–5 each
    economic_buyer: int = 0
    decision_criteria: int = 0
    decision_process: int = 0
    identify_pain: int = 0
    champion: int = 0
    total: int = 0
    verdict: str = ""        # At Risk | Progressing | Strong


class StakeholderEntry(BaseModel):
    name: str = ""
    title: str = ""
    role: str = ""           # Decision Maker | Influencer | Champion | Blocker
    email: str = ""
    notes: str = ""


class QualificationStatus(BaseModel):
    """BANT + MEDDIC qualification for one opportunity."""

    opportunity_id: str = ""
    bant: BANTScore = Field(default_factory=BANTScore)
    meddic: MEDDICScore = Field(default_factory=MEDDICScore)

    stakeholder_map: list[StakeholderEntry] = Field(default_factory=list)
    primary_pain_points: list[str] = Field(default_factory=list)
    current_solution: str = ""
    known_competitors: list[str] = Field(default_factory=list)

    recommended_next_action: str = ""
    discovery_questions_needed: list[str] = Field(default_factory=list)

    qualified_by: str = ""           # rep email
    qualified_at: str = ""
    updated_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Meeting Record
# ---------------------------------------------------------------------------

class MeetingRecord(BaseModel):
    """A scheduled sales meeting."""

    meeting_id: str = Field(default_factory=lambda: str(uuid4()))
    calendar_event_id: str = ""       # Google Calendar event ID
    title: str = ""
    meeting_type: str = ""            # discovery | demo | qbr | proposal_review | followup
    start_time: str = ""              # ISO-8601
    end_time: str = ""
    timezone: str = "UTC"
    meet_link: str = ""
    attendees: list[dict[str, str]] = Field(default_factory=list)  # [{name, email, role}]

    agenda: str = ""
    prep_brief: str = ""              # generated meeting prep brief

    crm_activity_id: str = ""        # HubSpot activity ID
    opportunity_id: str = ""
    lead_id: str = ""

    status: str = "scheduled"        # scheduled | completed | cancelled | rescheduled
    outcome_notes: str = ""

    invite_sent: bool = False
    reminder_sent: bool = False
    followup_triggered: bool = False

    updated_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Proposal Record
# ---------------------------------------------------------------------------

class ProposalRecord(BaseModel):
    """A generated sales proposal and its delivery state."""

    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    opportunity_id: str = ""

    title: str = ""
    prospect_company: str = ""
    pricing_tier: str = ""
    seats: int = 0
    contract_term_months: int = 12
    list_price_annual: float = 0.0
    proposed_price_annual: float = 0.0
    effective_discount_pct: float = 0.0
    total_contract_value: float = 0.0
    payment_terms: str = "Annual upfront"

    roi_summary: str = ""
    case_studies_used: list[str] = Field(default_factory=list)

    # Document delivery
    gdrive_doc_url: str = ""         # Google Docs URL
    gdrive_doc_id: str = ""
    docusign_envelope_id: str = ""
    docusign_status: str = ""        # draft | sent | signed | voided

    # Approval
    discount_approved: bool = False
    approved_by: str = ""
    approval_notes: str = ""
    escalated_to_dealdesk: bool = False

    status: str = "draft"            # draft | sent | signed | rejected | expired

    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Opportunity State
# ---------------------------------------------------------------------------

class OpportunityState(BaseModel):
    """CRM deal snapshot — the top-level sales opportunity."""

    opportunity_id: str = Field(default_factory=lambda: str(uuid4()))
    crm_deal_id: str = ""            # HubSpot / Salesforce deal ID
    deal_name: str = ""
    company_name: str = ""
    company_domain: str = ""

    owner_email: str = ""
    stage: str = ""                  # prospecting | qualified | demo_scheduled |
    #                                   proposal_sent | negotiation | contract_sent |
    #                                   closed_won | closed_lost
    amount: float = 0.0
    currency: str = "USD"
    close_date: str = ""

    probability: float = 0.0         # 0–100
    weighted_value: float = 0.0      # amount * probability / 100

    pipeline_entry_date: str = ""
    days_in_stage: int = 0
    last_activity_date: str = ""
    last_activity_type: str = ""

    # Linked records (IDs only — full objects in leads/meetings/proposals dicts)
    lead_ids: list[str] = Field(default_factory=list)
    meeting_ids: list[str] = Field(default_factory=list)
    proposal_ids: list[str] = Field(default_factory=list)

    # Qualification
    qualification: QualificationStatus = Field(default_factory=QualificationStatus)

    # Flags
    at_risk: bool = False
    at_risk_reason: str = ""
    fast_track: bool = False
    escalated_to_dealdesk: bool = False

    # Next step
    next_action: str = ""
    next_action_due: str = ""

    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Full AURA Session Document
# ---------------------------------------------------------------------------

class AURASession(BaseModel):
    """Complete AURA session stored as a single Firestore document.

    One session per (user_id, session_id) pair.
    Sub-collections are intentionally flat dicts for atomic reads.
    """

    # Identity
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    rep_email: str = ""
    rep_name: str = ""

    # Active context pointers (IDs of the currently focused records)
    active_opportunity_id: str = ""
    active_lead_id: str = ""

    # Core data stores
    leads: dict[str, Any] = Field(default_factory=dict)            # lead_id → LeadData.model_dump()
    opportunities: dict[str, Any] = Field(default_factory=dict)    # opp_id → OpportunityState.model_dump()
    meetings: dict[str, Any] = Field(default_factory=dict)         # meeting_id → MeetingRecord.model_dump()
    proposals: dict[str, Any] = Field(default_factory=dict)        # proposal_id → ProposalRecord.model_dump()

    # Turn-level metadata
    last_intent: str = ""       # discovery | qualification | booking | proposal |
    #                              followup | revenue | dealdesk | unknown
    last_agent_routed: str = ""
    turn_count: int = 0
    conversation_summary: str = ""   # running summary injected into prompt

    # Timestamps
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    # ---------------------------------------------------------------------------
    # Typed accessors — return domain models, not raw dicts
    # ---------------------------------------------------------------------------

    def get_lead(self, lead_id: str) -> Optional[LeadData]:
        raw = self.leads.get(lead_id)
        return LeadData.model_validate(raw) if raw else None

    def get_opportunity(self, opp_id: str) -> Optional[OpportunityState]:
        raw = self.opportunities.get(opp_id)
        return OpportunityState.model_validate(raw) if raw else None

    def get_meeting(self, meeting_id: str) -> Optional[MeetingRecord]:
        raw = self.meetings.get(meeting_id)
        return MeetingRecord.model_validate(raw) if raw else None

    def get_proposal(self, proposal_id: str) -> Optional[ProposalRecord]:
        raw = self.proposals.get(proposal_id)
        return ProposalRecord.model_validate(raw) if raw else None

    # ---------------------------------------------------------------------------
    # Mutators
    # ---------------------------------------------------------------------------

    def upsert_lead(self, lead: LeadData) -> None:
        lead.updated_at = _now_iso()
        self.leads[lead.lead_id] = lead.model_dump()

    def upsert_opportunity(self, opp: OpportunityState) -> None:
        opp.updated_at = _now_iso()
        self.opportunities[opp.opportunity_id] = opp.model_dump()

    def upsert_meeting(self, meeting: MeetingRecord) -> None:
        meeting.updated_at = _now_iso()
        self.meetings[meeting.meeting_id] = meeting.model_dump()

    def upsert_proposal(self, proposal: ProposalRecord) -> None:
        proposal.updated_at = _now_iso()
        self.proposals[proposal.proposal_id] = proposal.model_dump()

    # ---------------------------------------------------------------------------
    # Merge helper — apply a partial-update dict without clobbering other fields
    # ---------------------------------------------------------------------------

    def merge(self, partial: dict[str, Any]) -> None:
        """Deep-merge `partial` into this session.

        Top-level dict fields (leads, opportunities, meetings, proposals) are
        merged key-by-key so one upsert doesn't clobber unrelated records.
        Scalar fields are replaced directly.
        """
        _DICT_FIELDS = {"leads", "opportunities", "meetings", "proposals"}
        for key, value in partial.items():
            if key in _DICT_FIELDS and isinstance(value, dict):
                current = getattr(self, key, {})
                current.update(value)
                setattr(self, key, current)
            else:
                setattr(self, key, value)
        self.updated_at = _now_iso()

    # ---------------------------------------------------------------------------
    # Context summary for prompt injection
    # ---------------------------------------------------------------------------

    def to_context_summary(self) -> str:
        """Return a compact session summary to inject into the orchestrator prompt."""
        lines = ["## Active Session Context"]

        if self.active_opportunity_id:
            opp = self.get_opportunity(self.active_opportunity_id)
            if opp:
                lines.append(
                    f"**Active Opportunity:** {opp.deal_name} — {opp.company_name} "
                    f"| Stage: {opp.stage} | Value: ${opp.amount:,.0f} | Close: {opp.close_date}"
                )
                q = opp.qualification
                if q.bant.total:
                    lines.append(
                        f"  • BANT: {q.bant.total}/20 ({q.bant.verdict}) | "
                        f"MEDDIC: {q.meddic.total}/30 ({q.meddic.verdict})"
                    )
                if opp.next_action:
                    lines.append(f"  • Next action: {opp.next_action} (due {opp.next_action_due})")

        if self.active_lead_id:
            lead = self.get_lead(self.active_lead_id)
            if lead:
                lines.append(
                    f"**Active Lead:** {lead.first_name} {lead.last_name} "
                    f"({lead.title} @ {lead.company_name}) | ICP: {lead.icp_score:.1f}/10 ({lead.icp_tier})"
                )

        open_meetings = [
            MeetingRecord.model_validate(m)
            for m in self.meetings.values()
            if m.get("status") == "scheduled"
        ]
        if open_meetings:
            lines.append(f"**Upcoming Meetings:** {len(open_meetings)}")
            for m in sorted(open_meetings, key=lambda x: x.start_time)[:3]:
                lines.append(f"  • {m.title} — {m.start_time[:16]} UTC")

        open_proposals = [
            ProposalRecord.model_validate(p)
            for p in self.proposals.values()
            if p.get("status") in ("draft", "sent")
        ]
        if open_proposals:
            lines.append(f"**Open Proposals:** {len(open_proposals)}")
            for p in open_proposals[:3]:
                lines.append(f"  • {p.title} — {p.status} | ${p.proposed_price_annual:,.0f}/yr")

        lines.append(f"**Last intent routed:** {self.last_intent or 'none'} (turn #{self.turn_count})")

        if self.conversation_summary:
            lines.append(f"\n**Conversation so far:** {self.conversation_summary}")

        return "\n".join(lines)
