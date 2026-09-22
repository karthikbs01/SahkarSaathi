"""Conservative follow-up resolution for retrieval queries only.

History supplies a subject and an active task, never evidence or legal facts.
Only user messages are inspected; the visible user question remains unchanged.
"""
from dataclasses import dataclass
import logging
import re


LOGGER = logging.getLogger(__name__)
CLARIFICATION = (
    "Please specify the scheme, cooperative issue, or procedure you mean, "
    "and the relevant state if applicable."
)

FOLLOW_UP_INTENTS = (
    ("documents", re.compile(
        r"^(?:what|which) documents? (?:do i need|are needed|required|should i (?:bring|submit|provide))\??$",
        re.I)),
    ("timeline", re.compile(
        r"^(?:how long (?:will|does|would) it take|what is the (?:time|timeline)|when will it (?:finish|be done))\??$",
        re.I)),
    ("destination", re.compile(
        r"^where (?:do|can|should) i (?:submit|report|file|complain|go)(?: (?:it|this))?\??$",
        re.I)),
    ("next_step", re.compile(
        r"^(?:what (?:should i do )?next|what is the next step)\??$", re.I)),
    ("appeal", re.compile(
        r"^(?:can i appeal|how (?:do|can|should) i appeal|what about (?:an )?appeal)\??$",
        re.I)),
    ("eligibility", re.compile(
        r"^(?:am i eligible|who is eligible|what (?:are the )?eligibility requirements?|"
        r"what could disqualify me|what (?:would|can) disqualify me)\??$", re.I)),
    ("missed_deadline", re.compile(
        r"^what if i missed (?:the|that) deadline\??$", re.I)),
)


@dataclass(frozen=True)
class ActiveContext:
    subject: str
    procedure: str
    key: str


def _follow_up_intent(text):
    value = text.strip()
    for name, pattern in FOLLOW_UP_INTENTS:
        if pattern.fullmatch(value):
            return name
    return None


def _contains(text, pattern):
    return bool(re.search(pattern, text, re.I))


def _active_context(text):
    """Derive retrieval labels from an explicit user turn without adding facts."""
    normalized = re.sub(r"\s+", " ", text).strip()
    crop = _contains(normalized, r"\b(?:crop|crop insurance|pmfby|insurance)\b")
    crop_loss = _contains(
        normalized,
        r"\b(?:damage[ds]?|damaged|loss|lost|heavy rain|flood|hail|calamity|post[- ]harvest)\b",
    )
    complaint = _contains(normalized, r"\b(?:complain|complaint|grievance|ombudsman)\b")
    membership = _contains(
        normalized,
        r"\b(?:become|join|membership|member|eligible|eligibility|disqualif(?:y|ied|ication))\b",
    )
    pacs = _contains(normalized, r"\bpacs\b")
    multistate = _contains(normalized, r"\bmulti[- ]state\b")
    deposit = _contains(normalized, r"\bdeposits?\b")

    if crop and crop_loss:
        scheme = "PMFBY crop insurance" if _contains(normalized, r"\bpmfby\b") else "crop insurance"
        return ActiveContext(
            subject=f"{scheme} after crop damage or loss",
            procedure="crop-loss reporting, loss assessment, and insurance claim",
            key="crop_loss_claim",
        )
    if complaint:
        issue = "deposit issue" if deposit else "cooperative issue"
        scope = " in a multi-state cooperative" if multistate else ""
        return ActiveContext(
            subject=f"{issue}{scope}",
            procedure=f"complaint or Ombudsman filing for the {issue}",
            key="complaint_filing",
        )
    if membership:
        state = " in Karnataka" if _contains(normalized, r"\bkarnataka\b") else (
            " in Maharashtra" if _contains(normalized, r"\bmaharashtra\b") else ""
        )
        scope = " of a multi-state cooperative" if multistate else state
        return ActiveContext(
            subject=f"cooperative society membership{scope}",
            procedure="admission to cooperative society membership and disqualification from admission",
            key="membership_eligibility",
        )
    if pacs:
        return ActiveContext(
            subject="PACS services",
            procedure="the PACS service or request described by the user",
            key="pacs_service",
        )
    if multistate:
        return ActiveContext(
            subject="multi-state cooperative issue",
            procedure="the multi-state cooperative procedure described by the user",
            key="multistate_issue",
        )
    return None


def _intent_focus(intent, context):
    procedure = context.procedure
    if context.key == "crop_loss_claim" and intent == "timeline":
        return (
            "general procedure for settlement of crop-loss insurance claims; time frame for "
            "loss assessment and claims payment"
        )
    focuses = {
        "documents": (
            f"required supporting documents for {procedure}"
        ),
        "timeline": (
            f"timeline, processing time, and duration for {procedure}"
        ),
        "destination": f"authority, channel, or filing location for {procedure}",
        "next_step": f"next procedural step in {procedure}",
        "appeal": f"appeal relating to {procedure}",
        "eligibility": f"eligibility or disqualification relating to {procedure}",
        "missed_deadline": f"missed deadline in {procedure}",
    }
    return focuses[intent]


def _english_user_turn(message, translate):
    text = message.content.strip()
    if len(text) > 1500:
        return None
    if re.search(r"[\u0900-\u097f\u0c80-\u0cff]", text):
        if not message.language or message.language == "en":
            return None
        return translate(text, message.language, "en")
    return text


def contextualize(question, history, translate, precheck, jurisdiction):
    """Return (internal retrieval query, clarification response)."""
    if not history:
        return question, None
    if re.fullmatch(r"what (?:about|if i have) another (?:problem|issue)\??", question, re.I):
        return question, CLARIFICATION

    intent = _follow_up_intent(question)
    if not intent:
        if re.search(r"\b(?:it|this|that|these|those|they|them|deadline|documents|appeal)\b", question, re.I):
            return question, CLARIFICATION
        return question, None

    contexts = []
    # Keep the existing four-message history window. Assistant turns are ignored.
    for message in reversed(history[-4:]):
        if message.role != "user":
            continue
        text = _english_user_turn(message, translate)
        if not text:
            return question, CLARIFICATION
        if _follow_up_intent(text):
            continue
        if precheck(text, jurisdiction):
            return question, CLARIFICATION
        context = _active_context(text)
        if context and context.key not in {item.key for item in contexts}:
            contexts.append(context)

    # More than one distinct active task is ambiguous; do not choose silently.
    if len(contexts) != 1:
        return question, CLARIFICATION

    context = contexts[0]
    intent_focus = _intent_focus(intent, context)
    # The generic wording is replaced in the internal query instead of being
    # appended: otherwise "documents" or "how long" remains the dominant
    # semantic signal. The user-visible question is retained by the caller.
    query = (
        f"Active subject: {context.subject}.\n"
        f"Active procedure/task: {context.procedure}.\n"
        f"Follow-up intent: {intent_focus}."
    )
    LOGGER.debug(
        "follow-up context active_subject=%r active_procedure=%r "
        "follow_up_intent=%r contextualized_query=%r",
        context.subject,
        context.procedure,
        intent,
        query,
    )
    return query, None
