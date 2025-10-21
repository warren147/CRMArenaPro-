# white_agent/white_mock.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="CRM Arena Pro — Mock White Agent", version="0.1")

# ───────────────────────────────────────────────────────────────────────────────
# Helpers to read the A2A history envelope that Green posts:
#   { "history": [ {"role":"user","content": <Observation>},
#                  {"role":"agent","content": <previous white msg>} ... ] }
# ───────────────────────────────────────────────────────────────────────────────

def _latest_observation(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Find last item whose content.type == "observation"
    for item in reversed(history):
        c = item.get("content") or {}
        if isinstance(c, dict) and c.get("type") == "observation":
            return c
    return {}

def _previous_white(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # Return the most recent white message if present
    for item in reversed(history):
        c = item.get("content") or {}
        if isinstance(c, dict) and c.get("role") == "white":
            return c
    return None

def _count_prior_proposals(history: List[Dict[str, Any]]) -> int:
    n = 0
    for item in history:
        c = item.get("content") or {}
        if c.get("type") == "action_proposal":
            n += 1
    return n

# ───────────────────────────────────────────────────────────────────────────────
# Domain knowledge baked into the mock (keeps the demo deterministic)
# ───────────────────────────────────────────────────────────────────────────────

GROUND_TRUTH = {
    # ServiceAgent (EM)
    "service_easy_001":   {"ids": ["Q-ROUTING-BILLING"]},
    "service_medium_002": {"ids": ["Q-ROUTING-BILLING"]},
    "service_hard_003":   {"ids": ["Q-ESCALATION-POLICY"]},
    # Analyst (F1)
    "analyst_easy_001":   {"text": "proof of purchase"},
    "analyst_medium_002": {"text": "proof of transaction and proof of purchase"},
    "analyst_hard_003":   {"text": "review policy proof of purchase escalation"},
    # Manager (MAPE)
    "manager_easy_001":   {"series": [12, 18, 27]},
    "manager_medium_002": {"series": [12, 18, 27]},
    "manager_hard_003":   {"series": [12, 18, 27, 36]},
}

# Mock data “fetched” by action proposals (these are deterministic echos)
MOCK_QUERIES = {
    "GET http://localhost/mock/queues?rule=Billing": {
        "status": 200,
        "body": {"queues": [{"QueueId": "Q-ROUTING-BILLING", "Rule": "Billing"}]}
    },
    "GET http://localhost/mock/queues?rule=Login%20Issue": {
        "status": 200,
        "body": {"queues": [{"QueueId": "Q-ROUTING-TECH", "Rule": "Login Issue"}]}
    },
    "GET http://localhost/mock/queues?rule=Policy%20Escalation": {
        "status": 200,
        "body": {"queues": [{"QueueId": "Q-ESCALATION-POLICY", "Rule": "Policy Escalation"}]}
    },
    "GET http://localhost/mock/kb?q=refund%20policy%20violation": {
        "status": 200,
        "body": {"hits": [{"id":"KA-2","title":"Customer Refund Policy"}]}
    },
    "GET http://localhost/mock/kb?q=warranty%20escalation%20protocol": {
        "status": 200,
        "body": {"hits": [{"id":"KA-3","title":"Escalation Protocol"}]}
    },
    "GET http://localhost/mock/cases?type=Login%20Issue&window=3m": {
        "status": 200,
        "body": {"series": [12, 18, 27]}
    }
}

def _make_action_proposal(session_id: str, turn: int, url: str, justification: str, expectation: str) -> Dict[str, Any]:
    """Create an action_proposal with an echoed, already-executed result (no real HTTP)."""
    method = "GET"
    key = f"{method} {url}"
    result = MOCK_QUERIES.get(key, {"status": 404, "body": {"error": "not found"}})
    return {
        "type": "action_proposal",
        "role": "white",
        "session_id": session_id,
        "turn": turn,
        "content": {
            "action": {
                "kind": "GET",
                "request": {
                    "url": url,
                    "headers": {"accept": "application/json"},
                    "body": None
                }
            },
            "justification": justification,
            "expectation": expectation,
            "white_agent_execution": {
                "request": {
                    "url": url,
                    "headers": {"accept": "application/json"},
                    "body": None
                },
                "result": {
                    "status": result["status"],
                    "headers": {"content-type": "application/json"},
                    "body": result["body"]
                }
            }
        }
    }

def _decision(session_id: str, turn: int, *, ids=None, text=None, series=None, plan: str = "", confidence: float = 0.9) -> Dict[str, Any]:
    answers: List[str] = []
    if ids:
        answers = list(ids)
    elif isinstance(text, str):
        answers = [text]
    elif isinstance(series, list):
        import json as _json
        answers = [_json.dumps(series)]
    return {
        "type": "decision",
        "role": "white",
        "session_id": session_id,
        "turn": turn,
        "content": {
            "answers": answers,
            "plan": plan,
            "confidence": confidence,
            # also provide structured fields for Green’s tolerant evaluator
            "ids": ids,
            "text": text,
            "series": series
        }
    }

# ───────────────────────────────────────────────────────────────────────────────
# A2A endpoints
# ───────────────────────────────────────────────────────────────────────────────

@app.get("/a2a/card")
async def card():
    return {"protocol": "A2A-0.1", "capabilities": ["action_proposal", "decision"]}

@app.post("/a2a/step")
async def step(payload: Dict[str, Any]):
    """
    The Green server POSTs: {"history": [ ... ]}
    We respond with one JSON A2A message: action_proposal or decision.
    """
    history = payload.get("history") or []
    if not isinstance(history, list) or not history:
        return JSONResponse(content={"error": "empty history"}, status_code=400)

    obs = _latest_observation(history)
    if not obs:
        return JSONResponse(content={"error": "no observation found"}, status_code=400)

    session_id = obs.get("session_id", "unknown")
    turn_next = max(1, int(obs.get("turn", 1)))  # we’ll use obs.turn as our reply turn
    case = (obs.get("content", {}).get("case") or {})
    instruction = (case.get("instruction") or "").lower()
    case_id = case.get("id", "")

    # How many proposals have we already sent in this session?
    prior_proposals = _count_prior_proposals(history)

    # ── ServiceAgent (EM)
    if case_id == "service_easy_001":
        return JSONResponse(content=_decision(session_id, turn_next,
            ids=GROUND_TRUTH[case_id]["ids"],
            plan="Billing issues route directly to Billing queue.",
            confidence=0.98
        ))

    if case_id == "service_medium_002":
        # 1st: propose reading the Billing queue; 2nd: decide
        if prior_proposals < 1:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/queues?rule=Billing",
                justification="Check which queue handles Billing cases.",
                expectation="Should return a queue with Rule=Billing."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
            ids=GROUND_TRUTH[case_id]["ids"],
            plan="Chose Billing over Login Issue after inspecting queues.",
            confidence=0.96
        ))

    if case_id == "service_hard_003":
        # 1st: KB search about refund policy; 2nd: fetch escalation queue; 3rd: decide
        if prior_proposals < 1:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/kb?q=refund%20policy%20violation",
                justification="Verify refund policy violation condition.",
                expectation="KB should reference refund policy."
            ))
        if prior_proposals < 2:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/queues?rule=Policy%20Escalation",
                justification="Find the Policy Escalation queue for routing.",
                expectation="Should return escalation queue ID."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
            ids=GROUND_TRUTH[case_id]["ids"],
            plan="Policy violation confirmed in KB; escalate to Policy Escalation queue.",
            confidence=0.94
        ))

    # ── Analyst (F1)
    if case_id == "analyst_easy_001":
        return JSONResponse(content=_decision(session_id, turn_next,
            text=GROUND_TRUTH[case_id]["text"],
            plan="Returned the credential required by the warranty process.",
            confidence=0.97
        ))

    if case_id == "analyst_medium_002":
        if prior_proposals < 1:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/kb?q=refund%20policy%20violation",
                justification="Locate policy covering both proofs.",
                expectation="KB mentioning proof of transaction and proof of purchase."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
            text=GROUND_TRUTH[case_id]["text"],
            plan="Synthesized both requirements from policy hits.",
            confidence=0.95
        ))

    if case_id == "analyst_hard_003":
        if prior_proposals < 1:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/kb?q=warranty%20escalation%20protocol",
                justification="Review escalation protocol.",
                expectation="KB that mentions escalation protocol."
            ))
        if prior_proposals < 2:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/kb?q=refund%20policy%20violation",
                justification="Confirm proof requirement before escalation.",
                expectation="KB mentioning proof of purchase."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
            text=GROUND_TRUTH[case_id]["text"],
            plan="Review policy, confirm proof requirement, then escalate as prescribed.",
            confidence=0.92
        ))

    # ── Manager (MAPE)
    if case_id == "manager_easy_001":
        return JSONResponse(content=_decision(session_id, turn_next,
            series=GROUND_TRUTH[case_id]["series"],
            plan="Reported the last 3 months case counts.",
            confidence=0.99
        ))

    if case_id == "manager_medium_002":
        if prior_proposals < 1:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/cases?type=Login%20Issue&window=3m",
                justification="Fetch 3-month series to compute the average/trend.",
                expectation="Series like [12,18,27]."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
            series=GROUND_TRUTH[case_id]["series"],  # keeping trend shape
            plan="Approximate monthly values reflecting upward trend.",
            confidence=0.93
        ))

    if case_id == "manager_hard_003":
        if prior_proposals < 1:
            return JSONResponse(content=_make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/cases?type=Login%20Issue&window=3m",
                justification="Fetch historical series to extrapolate next month.",
                expectation="Series like [12,18,27]."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
            series=GROUND_TRUTH[case_id]["series"],
            plan="Assuming growth persists, extrapolate to 36 for next month.",
            confidence=0.91
        ))

    # Fallback (unknown case): return a conservative decision
    return JSONResponse(content=_decision(session_id, turn_next,
        text="unknown",
        plan="No matching case handler; returning fallback answer.",
        confidence=0.2
    ))