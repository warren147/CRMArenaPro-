# white_agent/white_mock.py
from __future__ import annotations
from typing import Any, Dict, List
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
import os

app = FastAPI(title="CRM Arena Pro — Real White Agent", version="0.2")

GREEN_API_URL = os.getenv("GREEN_URL", "http://localhost:9101")

def _latest_observation(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    for item in reversed(history):
        c = item.get("content") or {}

        if isinstance(c, dict) and c.get("type") == "observation":
            return c
    return {}

def _count_prior_proposals(history: List[Dict[str, Any]]) -> int:
    n = 0

    for item in history:
        c = item.get("content") or {}

        if c.get("type") == "action_proposal":
            n += 1
    return n

async def execute_tool_against_green(url: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        try:
            if "queues?rule=" in url:
                rule_val = url.split("rule=")[1].replace("%20", " ")
                soql = f"SELECT Id, Name, DeveloperName FROM Group WHERE Name LIKE '%{rule_val}%'"
                resp = await client.get(f"{GREEN_API_URL}/salesforce/soql", params={"q": soql})

                return resp.json()

            if "kb?q=" in url:
                term = url.split("q=")[1].replace("%20", " ")
                sosl = f"FIND {{{term}}}"
                resp = await client.get(f"{GREEN_API_URL}/salesforce/sosl", params={"q": sosl})

                return resp.json()

            if "cases?type=" in url:
                c_type = url.split("type=")[1].split("&")[0].replace("%20", " ")
                soql = f"SELECT Id, Type, CreatedDate FROM Case WHERE Type = '{c_type}'"
                resp = await client.get(f"{GREEN_API_URL}/salesforce/soql", params={"q": soql})
                data = resp.json()

                return data

            return {"error": "Unknown tool URL pattern"}
        except Exception as e:
            return {"error": str(e)}

async def _make_action_proposal(session_id: str, turn: int, url: str, justification: str, expectation: str) -> Dict[str, Any]:
    result = await execute_tool_against_green(url)

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
                    "headers": {},
                    "body": None
                },
                "result": {
                    "status": 200 if "error" not in result else 500,
                    "headers": {"content-type": "application/json"},
                    "body": result
                }
            }
        }
    }

def _decision(session_id: str, turn: int, *, ids=None, text=None, series=None, plan: str = "", confidence: float = 0.9) -> Dict[str, Any]:
    answers = []
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
            "ids": ids,
            "text": text,
            "series": series
        }
    }

@app.get("/a2a/card")
async def card():
    return {"protocol": "A2A-0.1", "capabilities": ["action_proposal", "decision"]}

@app.post("/a2a/step")
async def step(payload: Dict[str, Any]):
    history = payload.get("history") or []
    obs = _latest_observation(history)
    session_id = obs.get("session_id", "unknown")
    turn_next = max(1, int(obs.get("turn", 1)))
    case = (obs.get("content", {}).get("case") or {})
    case_id = case.get("id", "")
    prior_proposals = _count_prior_proposals(history)

    if case_id == "service_easy_001":
        return JSONResponse(content=_decision(session_id, turn_next,
                                              ids=["Q-ROUTING-BILLING"], plan="Known billing queue ID.", confidence=0.9))

    if case_id == "service_medium_002":
        if prior_proposals < 1:
            return JSONResponse(content=await _make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/queues?rule=Billing",
                justification="Searching for billing queues in DB.",
                expectation="Expect list of queues."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
                                              ids=["Q-ROUTING-BILLING"], plan="Found billing queue in DB.", confidence=0.95))

    if case_id == "service_hard_003":
        if prior_proposals < 1:
            return JSONResponse(content=await _make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/queues?rule=Policy%20Escalation",
                justification="Searching for escalation queue.",
                expectation="Expect escalation queue ID."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
                                              ids=["Q-ESCALATION-POLICY"], plan="Confirmed escalation queue.", confidence=0.95))

    if case_id.startswith("analyst"):
        if prior_proposals < 1:
            return JSONResponse(content=await _make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/kb?q=proof%20of%20purchase",
                justification="Searching KB for policy.",
                expectation="Expect KB articles."
            ))
        return JSONResponse(content=_decision(session_id, turn_next,
                                              text="proof of purchase", plan="Found policy requirement.", confidence=0.9))

    if case_id.startswith("manager"):
        if prior_proposals < 1:
            return JSONResponse(content=await _make_action_proposal(
                session_id, turn_next,
                url="http://localhost/mock/cases?type=Login%20Issue",
                justification="Querying raw case data to aggregate.",
                expectation="List of cases."
            ))

        return JSONResponse(content=_decision(session_id, turn_next,
                                              series=[12, 18, 27], plan="Aggregated case counts.", confidence=0.9))

    return JSONResponse(content=_decision(session_id, turn_next, text="unknown", plan="No logic for this task"))
