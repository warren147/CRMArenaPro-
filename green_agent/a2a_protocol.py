# green_agent/a2a_protocol.py
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, validator
from enum import Enum
from urllib.parse import urlparse
import json

A2A_VERSION: str = "A2A-0.1"

class Role(str, Enum):
    GREEN = "green"
    WHITE = "white"

class MsgType(str, Enum):
    OBSERVATION     = "observation"
    ACTION_PROPOSAL = "action_proposal"
    DECISION        = "decision"
    FEEDBACK        = "feedback"

class HTTPMethod(str, Enum):
    GET = "GET"
    POST = "POST"

class HTTPRequest(BaseModel):
    url: str = Field(..., description="Absolute or relative URL the white agent accessed.")
    headers: Dict[str, Any] = Field(default_factory=dict)
    body: Optional[Dict[str, Any]] = Field(default=None)

    @validator("url")
    def non_empty_url(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("url must be a non-empty string")
        return v

class HTTPAction(BaseModel):
    kind: HTTPMethod
    request: HTTPRequest

class ExecutedResult(BaseModel):
    status: int = Field(..., ge=0, le=999)
    headers: Dict[str, Any] = Field(default_factory=dict)
    body: Optional[Dict[str, Any]] = Field(default=None)

class WhiteExecution(BaseModel):
    request: HTTPRequest
    result: ExecutedResult

class ActionContent(BaseModel):
    action: HTTPAction
    justification: Optional[str] = None
    expectation: Optional[str] = None
    white_agent_execution: Optional[WhiteExecution] = None

class Observation(BaseModel):
    type: Literal[MsgType.OBSERVATION] = MsgType.OBSERVATION
    role: Literal[Role.GREEN] = Role.GREEN
    session_id: str
    turn: int = Field(..., ge=1)
    content: Dict[str, Any]
    protocol: str = Field(default=A2A_VERSION)

class ActionProposal(BaseModel):
    type: Literal[MsgType.ACTION_PROPOSAL] = MsgType.ACTION_PROPOSAL
    role: Literal[Role.WHITE] = Role.WHITE
    session_id: str
    turn: int = Field(..., ge=1)
    content: ActionContent
    protocol: str = Field(default=A2A_VERSION)

class DecisionContent(BaseModel):
    answers: List[str] = Field(default_factory=list)
    plan: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Optional structured keys that some whites might return:
    ids: Optional[List[str]] = None
    text: Optional[str] = None
    series: Optional[List[float]] = None

class Decision(BaseModel):
    type: Literal[MsgType.DECISION] = MsgType.DECISION
    role: Literal[Role.WHITE] = Role.WHITE
    session_id: str
    turn: int = Field(..., ge=1)
    content: DecisionContent
    protocol: str = Field(default=A2A_VERSION)

class FeedbackValidation(BaseModel):
    action_valid: bool
    policy_violations: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

class FeedbackContent(BaseModel):
    ack: bool = True
    validation: FeedbackValidation
    observation: Optional[Dict[str, Any]] = None

class Feedback(BaseModel):
    type: Literal[MsgType.FEEDBACK] = MsgType.FEEDBACK
    role: Literal[Role.GREEN] = Role.GREEN
    session_id: str
    turn: int = Field(..., ge=1)
    content: FeedbackContent
    protocol: str = Field(default=A2A_VERSION)

# Union for convenience
A2AMessage = Union[Observation, ActionProposal, Decision, Feedback]

# History envelope models
class HistoryItem(BaseModel):
    role: Literal["user", "agent"]
    content: Dict[str, Any]  # an A2A message as dict

class HistoryEnvelope(BaseModel):
    history: List[HistoryItem]

# Helper factories
def make_observation(
    session_id: str,
    turn: int,
    *,
    context: str,
    case_id: str,
    instruction: str,
    schema: Optional[Dict[str, Any]] = None,
    constraints: Optional[Dict[str, Any]] = None,
) -> Observation:
    payload = {"context": context, "case": {"id": case_id, "instruction": instruction}}
    if schema: payload["schema"] = schema
    if constraints: payload["constraints"] = constraints
    return Observation(session_id=session_id, turn=turn, content=payload)

def make_feedback_ok(session_id: str, turn: int, notes: str, observation_echo: Dict[str, Any]) -> Feedback:
    return Feedback(
        session_id=session_id,
        turn=turn,
        content=FeedbackContent(
            ack=True,
            validation=FeedbackValidation(action_valid=True, notes=notes),
            observation=observation_echo,
        ),
    )

def make_feedback_error(session_id: str, turn: int, notes: str, violations: Optional[List[str]] = None) -> Feedback:
    return Feedback(
        session_id=session_id,
        turn=turn,
        content=FeedbackContent(
            ack=True,
            validation=FeedbackValidation(
                action_valid=False,
                policy_violations=violations or [],
                notes=notes,
            ),
            observation=None,
        ),
    )

class ProposalPolicy(BaseModel):
    allowed_domains: List[str] = Field(default_factory=lambda: ["example.org", "localhost"])
    max_body_bytes: int = 200_000
    allow_methods: List[HTTPMethod] = Field(default_factory=lambda: [HTTPMethod.GET, HTTPMethod.POST])

def _host_from_url(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""

def _json_size(obj: Any) -> int:
    try:
        return len(json.dumps(obj))
    except Exception:
        return 0

def validate_action_proposal(proposal: ActionProposal, policy: ProposalPolicy) -> FeedbackValidation:
    notes: List[str] = []
    ok = True

    method = proposal.content.action.kind
    if method not in policy.allow_methods:
        ok = False; notes.append(f"Method {method} not allowed")

    host = _host_from_url(proposal.content.action.request.url)
    if host and policy.allowed_domains and host not in policy.allowed_domains:
        ok = False; notes.append(f"Domain '{host}' not in allowlist")

    req_size = _json_size(proposal.content.action.request.dict())
    if req_size > policy.max_body_bytes:
        ok = False; notes.append(f"Request payload too large ({req_size} > {policy.max_body_bytes})")

    if proposal.content.white_agent_execution:
        res_size = _json_size(proposal.content.white_agent_execution.result.dict())
        if res_size > policy.max_body_bytes:
            ok = False; notes.append(f"Result payload too large ({res_size} > {policy.max_body_bytes})")

    return FeedbackValidation(
        action_valid=ok,
        policy_violations=[] if ok else notes,
        notes="; ".join(notes) if notes else "ok"
    )

def validate_decision(decision: Decision) -> FeedbackValidation:
    ok = bool(decision.content.answers or decision.content.ids or decision.content.text or decision.content.series)
    return FeedbackValidation(action_valid=ok, policy_violations=[] if ok else ["No answer provided"], notes="ok" if ok else "missing answer")

def pack_history(observation: Observation, previous_white: Optional[A2AMessage] = None) -> HistoryEnvelope:
    items: List[HistoryItem] = [HistoryItem(role="user", content=observation.dict())]
    if previous_white is not None:
        items.append(HistoryItem(role="agent", content=previous_white.dict()))
    return HistoryEnvelope(history=items)