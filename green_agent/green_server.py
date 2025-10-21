# green_agent/green_server.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import os, uuid, httpx, json
from .a2a_protocol import HistoryEnvelope, HistoryItem

# Build a FULL envelope from everything we've stored so far
def _build_full_history_envelope(state) -> dict:
    from .a2a_protocol import HistoryEnvelope, HistoryItem
    items: list[HistoryItem] = []
    for msg in state.history:
        if isinstance(msg, dict):
            if msg.get("type") == "observation" and msg.get("role") == "green":
                items.append(HistoryItem(role="user", content=msg))
            elif msg.get("role") == "white":
                items.append(HistoryItem(role="agent", content=msg))
    return HistoryEnvelope(history=items).dict()

from .a2a_protocol import (
    A2A_VERSION, Observation, ActionProposal, Decision, Feedback,
    make_observation, make_feedback_ok, make_feedback_error,
    pack_history, validate_action_proposal, validate_decision,
    ProposalPolicy,
)
from .evaluator import evaluate_decision_for_task  # <-- centralized metrics

WHITE_URL = os.getenv("A2A_WHITE_URL", "http://localhost:9100/a2a/step")
ALLOWED_DOMAINS = [d.strip() for d in os.getenv("A2A_ALLOWED_DOMAINS", "localhost,example.org").split(",") if d.strip()]
MAX_ROUNDS = 100

def _demo_tasks() -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    tasks += [
        dict(task_id="service_easy_001", persona="ServiceAgent", difficulty="easy",
             instruction="Find the queue handling Billing cases and return its Queue ID.",
             success_criteria="exact_match_ids", ground_truth={"id_list": ["Q-ROUTING-BILLING"]}),
        dict(task_id="service_medium_002", persona="ServiceAgent", difficulty="medium",
             instruction="Compare Billing and Login Issue queues and choose the correct one for a customer billing error.",
             success_criteria="exact_match_ids", ground_truth={"id_list": ["Q-ROUTING-BILLING"]}),
        dict(task_id="service_hard_003", persona="ServiceAgent", difficulty="hard",
             instruction="If a billing error violates refund policy, escalate it to the Policy Escalation queue. Return that Queue ID.",
             success_criteria="exact_match_ids", ground_truth={"id_list": ["Q-ESCALATION-POLICY"]}),
    ]
    tasks += [
        dict(task_id="analyst_easy_001", persona="Analyst", difficulty="easy",
             instruction="Find which credential is required before performing a warranty replacement.",
             success_criteria="f1", ground_truth={"answer_tokens": list(set("proof of purchase".split()))}),
        dict(task_id="analyst_medium_002", persona="Analyst", difficulty="medium",
             instruction="Identify the policy that mentions both 'proof of transaction' and 'proof of purchase' requirements.",
             success_criteria="f1", ground_truth={"answer_tokens": list(set("proof of transaction proof of purchase".split()))}),
        dict(task_id="analyst_hard_003", persona="Analyst", difficulty="hard",
             instruction="Using policy and escalation documentation, summarize the process before escalating a warranty dispute.",
             success_criteria="f1", ground_truth={"answer_tokens": list(set("review policy proof of purchase escalation".split()))}),
    ]
    tasks += [
        dict(task_id="manager_easy_001", persona="Manager", difficulty="easy",
             instruction="Report the monthly counts of Login Issue cases for the last 3 months as [M-2, M-1, M].",
             success_criteria="mape", ground_truth={"series": [12, 18, 27]}),
        dict(task_id="manager_medium_002", persona="Manager", difficulty="medium",
             instruction="Compute the average monthly count over the last 3 months and return approximate monthly values [M-2,M-1,M] that reflect the trend.",
             success_criteria="mape", ground_truth={"series": [12, 18, 27]}),
        dict(task_id="manager_hard_003", persona="Manager", difficulty="hard",
             instruction="Predict the next month assuming growth continues. Return [M-2, M-1, M, M+1].",
             success_criteria="mape", ground_truth={"series": [12, 18, 27, 36]}),
    ]
    return tasks

TASKS = _demo_tasks()

def pick_task(persona: str, difficulty: str) -> Dict[str, Any]:
    for t in TASKS:
        if t["persona"] == persona and t["difficulty"] == difficulty:
            return t
    raise KeyError(f"No task for persona={persona}, difficulty={difficulty}")

class SessionState:
    def __init__(self, session_id: str, persona: str, difficulty: str, task: Dict[str, Any]):
        self.session_id = session_id
        self.persona = persona
        self.difficulty = difficulty
        self.task = task
        self.turn = 1
        self.last_white: Optional[Dict[str, Any]] = None
        self.history: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "persona": self.persona,
            "difficulty": self.difficulty,
            "task": self.task,
            "turn": self.turn,
            "last_white": self.last_white,
            "history": self.history,
        }

SESSIONS: Dict[str, SessionState] = {}

app = FastAPI(title="CRM Arena Pro — Green A2A Server", version="0.1")
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:9200", "http://127.0.0.1:9200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/a2a/card")
async def card():
    return {"protocol": A2A_VERSION, "capabilities": ["observation", "feedback"], "tasks": [t["task_id"] for t in TASKS]}

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    state = SESSIONS.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session not found")
    return state.to_dict()

async def _post_to_white(history_payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(WHITE_URL, json=history_payload)
        resp.raise_for_status()
        return resp.json()

def _policy() -> ProposalPolicy:
    return ProposalPolicy(allowed_domains=ALLOWED_DOMAINS)

@app.post("/a2a/start")
async def start_a2a(
    persona: str = Query("ServiceAgent", description="ServiceAgent | Analyst | Manager"),
    difficulty: str = Query("easy", description="easy | medium | hard"),
):
    try:
        task = pick_task(persona, difficulty)
    except KeyError as e:
        raise HTTPException(400, str(e))

    session_id = str(uuid.uuid4())
    state = SessionState(session_id, persona, difficulty, task)
    SESSIONS[session_id] = state

    obs = make_observation(
        session_id=session_id,
        turn=state.turn,
        context="CRM Arena Pro evaluation session",
        case_id=task["task_id"],
        instruction=task["instruction"],
        constraints={"max_round": MAX_ROUNDS, "metric": task["success_criteria"]},
        schema={"note": "In A2A mode, white executes its own tools and echoes request+result."}
    )
    state.history.append(obs.dict())

    history_payload = _build_full_history_envelope(state)

    try:
        white_msg = await _post_to_white(history_payload)
    except Exception as e:
        raise HTTPException(502, f"white agent error: {e}")

    state.last_white = white_msg
    state.turn += 1
    state.history.append(white_msg)

    if white_msg.get("type") == "action_proposal":
        try:
            proposal = ActionProposal(**white_msg)
        except Exception as e:
            fb = make_feedback_error(session_id, state.turn, f"Malformed proposal: {e}")
            state.history.append(fb.dict())
            return JSONResponse(content={"session_id": session_id, "feedback": fb.dict()})
        v = validate_action_proposal(proposal, _policy())
        fb = make_feedback_ok(session_id, state.turn, v.notes or "ok", observation_echo=proposal.content.dict())
        state.history.append(fb.dict())
        return JSONResponse(content={"session_id": session_id, "feedback": fb.dict(), "done": False})

    if white_msg.get("type") == "decision":
        try:
            decision = Decision(**white_msg)
        except Exception as e:
            raise HTTPException(400, f"Malformed decision: {e}")
        v = validate_decision(decision)
        scores = evaluate_decision_for_task(task, decision.content.dict())
        return {"session_id": session_id, "validation": v.dict(), "scores": scores, "done": True}

    return {"session_id": session_id, "note": "unknown white message type", "white_msg": white_msg}

@app.post("/a2a/continue")
async def continue_a2a(session_id: str):
    state = SESSIONS.get(session_id)
    if not state:
        raise HTTPException(404, "session not found")
    if state.turn > MAX_ROUNDS:
        return {"session_id": session_id, "note": "max rounds reached"}

    obs = make_observation(
        session_id=session_id,
        turn=state.turn,
        context="CRM Arena Pro follow-up",
        case_id=state.task["task_id"],
        instruction=state.task["instruction"],
        constraints={"max_round": MAX_ROUNDS, "metric": state.task["success_criteria"]},
    )
    state.history.append(obs.dict())

    items = [HistoryItem(role="user", content=obs.dict())]
    for msg in state.history:
        if isinstance(msg, dict) and msg.get("role") == "white":
            items.append(HistoryItem(role="agent", content=msg))
    history = HistoryEnvelope(history=items)

    prev_white = None
    if state.last_white and state.last_white.get("type") == "action_proposal":
        prev_white = ActionProposal(**state.last_white)

    history = pack_history(obs, previous_white=prev_white)
    try:
        white_msg = await _post_to_white(history.dict())
    except Exception as e:
        raise HTTPException(502, f"white agent error: {e}")

    state.last_white = white_msg
    state.turn += 1
    state.history.append(white_msg)

    if white_msg.get("type") == "action_proposal":
        proposal = ActionProposal(**white_msg)
        v = validate_action_proposal(proposal, _policy())
        fb = make_feedback_ok(state.session_id, state.turn, v.notes or "ok", observation_echo=proposal.content.dict())
        state.history.append(fb.dict())
        return {"session_id": state.session_id, "feedback": fb.dict(), "done": False}

    if white_msg.get("type") == "decision":
        decision = Decision(**white_msg)
        v = validate_decision(decision)
        scores = evaluate_decision_for_task(state.task, decision.content.dict())
        return {"session_id": state.session_id, "validation": v.dict(), "scores": scores, "done": True}

    return {"session_id": state.session_id, "note": "unknown white message type", "white_msg": white_msg}