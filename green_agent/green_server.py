# green_agent/green_server.py

from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
import os, uuid, httpx
import logging
from datasets import load_dataset
from .a2a_protocol import (A2A_VERSION, ActionProposal, Decision, make_observation, make_feedback_ok, make_feedback_error, validate_action_proposal, validate_decision, ProposalPolicy, HistoryEnvelope, HistoryItem)
from .database import db
from .evaluator import evaluate_decision_for_task

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("green.server")
WHITE_URL = os.getenv("A2A_WHITE_URL", "http://localhost:9100/a2a/step")
ALLOWED_DOMAINS = [d.strip() for d in os.getenv("A2A_ALLOWED_DOMAINS", "localhost,example.org").split(",") if d.strip()]
MAX_ROUNDS = 15

def load_tasks_from_hf() -> List[Dict[str, Any]]:
    loaded_tasks = []

    try:
        logger.info("Loading Tasks from Hugging Face (Config: CRMArenaPro)...")

        ds = load_dataset("Salesforce/CRMArenaPro", "CRMArenaPro", split="b2b")

        for i, row in enumerate(ds.select(range(min(50, len(ds))))):
            instruction = row.get("query") or row.get("question") or row.get("instruction") or "Unknown instruction"
            answer_raw = str(row.get("answer", ""))
            skill = row.get("skill", "General")
            persona_map = {
                "Workflow Execution": "ServiceAgent",
                "Database Querying": "Analyst",
                "Numerical Computation": "Manager"
            }
            persona = persona_map.get(skill, "ServiceAgent")
            success_criteria = "f1"
            ground_truth = {"answer_tokens": answer_raw.split()}

            if "Workflow" in skill:
                success_criteria = "exact_match_ids"
                ground_truth = {"id_list": [answer_raw]}
            elif "Numerical" in skill:
                success_criteria = "mape"

                try:
                    import json

                    clean_ans = answer_raw.replace("'", '"')

                    if "[" in clean_ans:
                        series = json.loads(clean_ans)
                    else:
                        series = [float(clean_ans)]

                    ground_truth = {"series": series}
                except:
                    ground_truth = {"series": []}

            task = {
                "task_id": f"hf_crm_{i}",
                "persona": persona,
                "difficulty": "medium",
                "instruction": instruction,
                "success_criteria": success_criteria,
                "ground_truth": ground_truth,
                "original_skill": skill
            }

            loaded_tasks.append(task)

        logger.info(f"Successfully loaded {len(loaded_tasks)} tasks from Hugging Face.")

        return loaded_tasks

    except Exception as e:
        logger.error(f"Failed to load HF Tasks: {e}. Falling back to Demo Tasks.")

        return _demo_tasks_fallback()

def _demo_tasks_fallback() -> List[Dict[str, Any]]:
    return [
        dict(task_id="fallback_01", persona="ServiceAgent", difficulty="easy",
             instruction="Find the queue handling Billing cases (Fallback Mode).",
             success_criteria="exact_match_ids", ground_truth={"id_list": ["Q-ROUTING-BILLING"]}),
    ]

TASKS = load_tasks_from_hf()

def pick_task(persona: str, difficulty: str) -> Dict[str, Any]:
    candidates = [t for t in TASKS if t["persona"] == persona]

    if not candidates:
        candidates = TASKS

    return candidates[0]

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

app = FastAPI(title="CRM Arena Pro — Green Server (HF Integrated)", version="0.3")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _build_full_history_envelope(state) -> dict:
    items = []

    for msg in state.history:
        if isinstance(msg, dict):
            role = "user" if msg.get("role") == "green" else "agent"

            items.append(HistoryItem(role=role, content=msg))

    return HistoryEnvelope(history=items).dict()

async def _post_to_white(history_payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(WHITE_URL, json=history_payload)

        resp.raise_for_status()

        return resp.json()

def _policy() -> ProposalPolicy:
    return ProposalPolicy(allowed_domains=ALLOWED_DOMAINS)

@app.get("/salesforce/soql")
async def soql_proxy(q: str = Query(..., description="SOQL Query")):
    return db.execute_soql(q)

@app.get("/salesforce/sosl")
async def sosl_proxy(q: str = Query(..., description="SOSL Search")):
    return db.execute_sosl(q)

@app.get("/a2a/card")
async def card():
    return {
        "protocol": A2A_VERSION,
        "capabilities": ["observation", "feedback"],
        "tasks_loaded": len(TASKS),
        "sample_task_ids": [t["task_id"] for t in TASKS[:5]]
    }

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    state = SESSIONS.get(session_id)

    if not state:
        raise HTTPException(status_code=404, detail="session not found")

    return state.to_dict()

@app.post("/a2a/start")
async def start_a2a(
        persona: str = Query("ServiceAgent"),
        difficulty: str = Query("easy"),
):
    try:
        task = pick_task(persona, difficulty)
    except Exception as e:
        raise HTTPException(400, f"Task selection failed: {e}")

    session_id = str(uuid.uuid4())
    state = SessionState(session_id, persona, difficulty, task)
    SESSIONS[session_id] = state

    obs = make_observation(
        session_id=session_id,
        turn=state.turn,
        context="CRM Arena Pro Evaluation (HF Dataset)",
        case_id=task["task_id"],
        instruction=task["instruction"],
        constraints={"max_round": MAX_ROUNDS, "metric": task["success_criteria"]},
        schema={"endpoints": ["/salesforce/soql", "/salesforce/sosl"]}
    )

    state.history.append(obs.dict())

    history_payload = _build_full_history_envelope(state)

    try:
        white_msg = await _post_to_white(history_payload)
    except Exception as e:
        raise HTTPException(502, f"White Agent unavailable: {e}")

    state.last_white = white_msg
    state.turn += 1
    state.history.append(white_msg)

    return process_white_response(session_id, state, white_msg)

@app.post("/a2a/continue")
async def continue_a2a(session_id: str):
    state = SESSIONS.get(session_id)

    if not state:
        raise HTTPException(404, "session not found")
    if state.turn > MAX_ROUNDS:
        return {"session_id": session_id, "note": "max rounds reached", "done": True}

    obs = make_observation(
        session_id=session_id,
        turn=state.turn,
        context="Follow-up turn",
        case_id=state.task["task_id"],
        instruction=state.task["instruction"],
    )

    state.history.append(obs.dict())

    history_payload = _build_full_history_envelope(state)

    try:
        white_msg = await _post_to_white(history_payload)
    except Exception as e:
        raise HTTPException(502, f"White Agent error: {e}")

    state.last_white = white_msg
    state.turn += 1

    state.history.append(white_msg)

    return process_white_response(session_id, state, white_msg)

def process_white_response(session_id: str, state: SessionState, white_msg: Dict[str, Any]):
    msg_type = white_msg.get("type")

    if msg_type == "action_proposal":
        try:
            proposal = ActionProposal(**white_msg)
            v = validate_action_proposal(proposal, _policy())
            fb = make_feedback_ok(
                session_id,
                state.turn,
                v.notes or "Action approved",
                observation_echo=proposal.content.dict()
            )

            state.history.append(fb.dict())

            return {"session_id": session_id, "feedback": fb.dict(), "done": False}
        except Exception as e:
            fb = make_feedback_error(session_id, state.turn, f"Invalid proposal: {e}")

            state.history.append(fb.dict())

            return {"session_id": session_id, "feedback": fb.dict(), "done": False}

    elif msg_type == "decision":
        try:
            decision = Decision(**white_msg)
            v = validate_decision(decision)
            scores = evaluate_decision_for_task(
                state.task,
                decision.content.dict(),
                state.task["instruction"]
            )

            return {"session_id": session_id, "validation": v.dict(), "scores": scores, "done": True}
        except Exception as e:
            raise HTTPException(400, f"Invalid decision: {e}")

    return {"session_id": session_id, "note": "Unknown message type", "white_msg": white_msg}
