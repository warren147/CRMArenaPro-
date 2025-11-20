# green_agent/a2a_protocol.py
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, validator
from enum import Enum

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
    url: str = Field(..., description="URL accessed.")
    headers: Dict[str, Any] = Field(default_factory=dict)
    body: Optional[Dict[str, Any]] = Field(default=None)

    @validator("url")
    def non_empty_url(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("url must be string")

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
    turn: int
    content: Dict[str, Any]
    protocol: str = A2A_VERSION

class ActionProposal(BaseModel):
    type: Literal[MsgType.ACTION_PROPOSAL] = MsgType.ACTION_PROPOSAL
    role: Literal[Role.WHITE] = Role.WHITE
    session_id: str
    turn: int
    content: ActionContent
    protocol: str = A2A_VERSION

class DecisionContent(BaseModel):
    answers: List[str] = []
    plan: Optional[str] = None
    confidence: float = 0.0
    # Optional structured keys that some whites might return:
    ids: Optional[List[str]] = None
    text: Optional[str] = None
    series: Optional[List[float]] = None

class Decision(BaseModel):
    type: Literal[MsgType.DECISION] = MsgType.DECISION
    role: Literal[Role.WHITE] = Role.WHITE
    session_id: str
    turn: int
    content: DecisionContent
    protocol: str = A2A_VERSION

class FeedbackValidation(BaseModel):
    action_valid: bool
    policy_violations: List[str] = []
    notes: Optional[str] = None

class FeedbackContent(BaseModel):
    ack: bool = True
    validation: FeedbackValidation
    observation: Optional[Dict[str, Any]] = None

class Feedback(BaseModel):
    type: Literal[MsgType.FEEDBACK] = MsgType.FEEDBACK
    role: Literal[Role.GREEN] = Role.GREEN
    session_id: str
    turn: int
    content: FeedbackContent
    protocol: str = A2A_VERSION

# Union for convenience
A2AMessage = Union[Observation, ActionProposal, Decision, Feedback]

# History envelope models
class HistoryItem(BaseModel):
    role: Literal["user", "agent"]
    content: Dict[str, Any]  # an A2A message as dict

class HistoryEnvelope(BaseModel):
    history: List[HistoryItem]

def make_observation(session_id, turn, *, context, case_id, instruction, schema=None, constraints=None):
    payload = {"context": context, "case": {"id": case_id, "instruction": instruction}}

    if schema:
        payload["schema"] = schema

    if constraints:
        payload["constraints"] = constraints

    return Observation(session_id=session_id, turn=turn, content=payload)

def make_feedback_ok(session_id, turn, notes, observation_echo):
    return Feedback(session_id=session_id, turn=turn, content=FeedbackContent(ack=True, validation=FeedbackValidation(action_valid=True, notes=notes), observation=observation_echo))

def make_feedback_error(session_id, turn, notes, violations=None):
    return Feedback(session_id=session_id, turn=turn, content=FeedbackContent(ack=True, validation=FeedbackValidation(action_valid=False, policy_violations=violations or [], notes=notes)))

class ProposalPolicy(BaseModel):
    allowed_domains: List[str] = ["example.org", "localhost"]
    max_body_bytes: int = 200_000
    allow_methods: List[HTTPMethod] = [HTTPMethod.GET, HTTPMethod.POST]

def validate_action_proposal(proposal: ActionProposal, policy: ProposalPolicy) -> FeedbackValidation:
    return FeedbackValidation(action_valid=True, notes="ok")

def validate_decision(decision: Decision) -> FeedbackValidation:
    ok = bool(decision.content.answers or decision.content.ids or decision.content.text or decision.content.series)

    return FeedbackValidation(action_valid=ok, notes="ok" if ok else "missing answer")

def pack_history(observation, previous_white=None):
    items = [HistoryItem(role="user", content=observation.dict())]

    if previous_white:
        items.append(HistoryItem(role="agent", content=previous_white.dict()))

    return HistoryEnvelope(history=items)
