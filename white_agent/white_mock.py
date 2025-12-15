# white_agent/white_mock.py

from __future__ import annotations
from typing import Any, Dict
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
import os
import random

app = FastAPI(title="CRM Arena Pro — White Agent (Universal Mock)", version="0.3")

GREEN_API_URL = os.getenv("GREEN_URL", "http://localhost:9101")

async def _make_random_proposal(session_id: str, turn: int) -> Dict[str, Any]:
    search_terms = ["billing", "refund", "policy", "escalation", "acme"]
    term = random.choice(search_terms)
    url = f"http://localhost/mock/kb?q={term}"

    async with httpx.AsyncClient() as client:
        try:
            await client.get(f"{GREEN_API_URL}/salesforce/sosl", params={"q": f"FIND {{{term}}}"})
        except:
            pass

    return {
        "type": "action_proposal",
        "role": "white",
        "session_id": session_id,
        "turn": turn,
        "content": {
            "action": {
                "kind": "GET",
                "request": {"url": url, "headers": {}, "body": None}
            },
            "justification": f"I need to look up info about {term}",
            "expectation": "Hoping to find relevant KB articles.",
            "white_agent_execution": {
                "request": {"url": url, "headers": {}, "body": None},
                "result": {"status": 200, "headers": {}, "body": {"searchRecords": []}}
            }
        }
    }

def _make_dummy_decision(session_id: str, turn: int) -> Dict[str, Any]:
    return {
        "type": "decision",
        "role": "white",
        "session_id": session_id,
        "turn": turn,
        "content": {
            "answers": ["I am just a mock agent."],
            "plan": "I tried my best but I am hardcoded.",
            "confidence": 0.1,
            "ids": ["000-DUMMY"],
            "text": "dummy answer",
            "series": [10, 20, 30]
        }
    }

@app.post("/a2a/step")
async def step(payload: Dict[str, Any]):
    history = payload.get("history") or []
    last_msg = history[-1]["content"] if history else {}
    session_id = last_msg.get("session_id", "unknown")
    turn = last_msg.get("turn", 1)
    my_turns = sum(1 for h in history if h.get("role") == "agent")

    if my_turns < 1:
        return JSONResponse(content=await _make_random_proposal(session_id, turn))
    else:
        return JSONResponse(content=_make_dummy_decision(session_id, turn))
