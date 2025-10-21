# green_agent/evaluator.py
from __future__ import annotations
from typing import Any, Dict, List, Iterable
import json

def _tokens(s: str) -> List[str]:
    if not isinstance(s, str):
        return []
    return [t for t in s.lower().split() if t]

def f1_text(pred_text: str, gold_tokens: Iterable[str]) -> float:
    P, G = set(_tokens(pred_text)), set(gold_tokens or [])
    if not P or not G:
        return 0.0
    inter = len(P & G)
    return round(2 * inter / (len(P) + len(G)), 3)

def exact_match_ids(pred_ids: Iterable[str], gold_ids: Iterable[str]) -> int:
    try:
        return int(sorted(set(pred_ids or [])) == sorted(set(gold_ids or [])))
    except Exception:
        return 0

def mape(pred_series: List[float], gold_series: List[float]) -> float:
    if not isinstance(pred_series, list) or not isinstance(gold_series, list):
        return 1.0
    if len(pred_series) != len(gold_series) or len(gold_series) == 0:
        return 1.0
    eps = 1e-9
    err = 0.0
    for p, g in zip(pred_series, gold_series):
        try:
            p = float(p); g = float(g)
        except Exception:
            return 1.0
        denom = abs(g) if abs(g) > eps else eps
        err += abs(p - g) / denom
    return round(err / len(gold_series), 3)

def _extract_ids_from_decision(decision_content: Dict[str, Any]) -> List[str]:
    if isinstance(decision_content.get("ids"), list):
        return [str(x) for x in decision_content["ids"]]
    answers = decision_content.get("answers") or []
    return [str(answers[0])] if answers else []

def _extract_text_from_decision(decision_content: Dict[str, Any]) -> str:
    if isinstance(decision_content.get("text"), str):
        return decision_content["text"]
    answers = decision_content.get("answers") or []
    return str(answers[0]) if answers else ""

def _extract_series_from_decision(decision_content: Dict[str, Any]) -> List[float]:
    if isinstance(decision_content.get("series"), list):
        return decision_content["series"]
    answers = decision_content.get("answers") or []
    if answers and isinstance(answers[0], str):
        try:
            parsed = json.loads(answers[0])
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []

def evaluate_decision_for_task(task: Dict[str, Any], decision_content: Dict[str, Any]) -> Dict[str, Any]:
    crit = task.get("success_criteria")
    gt   = task.get("ground_truth", {})

    if crit == "exact_match_ids":
        gold_ids = list(gt.get("id_list") or [])
        pred_ids = _extract_ids_from_decision(decision_content)
        return {"EM": exact_match_ids(pred_ids, gold_ids)}

    if crit == "f1":
        gold_tokens = list(gt.get("answer_tokens") or [])
        pred_text   = _extract_text_from_decision(decision_content)
        return {"F1": f1_text(pred_text, gold_tokens)}

    if crit == "mape":
        gold_series = list(gt.get("series") or [])
        pred_series = _extract_series_from_decision(decision_content)
        return {"MAPE": mape(pred_series, gold_series)}

    return {"note": f"unknown success_criteria: {crit}"}