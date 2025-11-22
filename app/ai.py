import json
import os
from typing import Any, Dict, List, TypedDict


class MissingDepsError(RuntimeError):
    pass


def _get_llm():
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception as e:
        raise MissingDepsError(
            "LangChain Google Generative AI integration not installed. Install 'langchain-google-genai' and 'google-generativeai'."
        ) from e

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is required.")

    # Default to a model name supported by v1beta generateContent.
    # Some environments/libraries use v1beta where the "-latest" alias is not available.
    # Normalize by stripping a trailing "-latest" if present.
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if model_name.endswith("-latest"):
        model_name = model_name[: -len("-latest")]
    # Low temperature for deterministic structure. Pass api_key explicitly to avoid
    # environments with ADC/OAuth taking precedence and causing 401 errors.
    return ChatGoogleGenerativeAI(model=model_name, temperature=0, api_key=api_key)


def _clean_and_parse_json(text: str) -> List[Dict[str, Any]]:
    raw = text.strip()
    # Remove common markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


class RulesState(TypedDict, total=False):
    policy_text: str
    scope: str
    raw_output: str
    rules: List[Dict[str, Any]]
    parsed_ok: bool


def extract_rules_with_langgraph(policy_text: str, scope: str = "both") -> List[Dict[str, Any]]:
    try:
        from langgraph.graph import StateGraph, END
        from langchain.prompts import ChatPromptTemplate
    except Exception as e:
        raise MissingDepsError(
            "LangGraph or LangChain not installed. Install 'langgraph' and 'langchain'."
        ) from e

    llm = _get_llm()

    # Stricter instruction with explicit schema examples to improve JSON compliance
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You extract structured, machine-checkable HR rules from policy text.\n"
                "Return ONLY a JSON array (no prose, no keys other than specified).\n"
                "Each item must contain: rule_code, description, category, severity, check_type, params.\n"
                "- category: one of ['leave','benefit'] (respect requested scope strictly).\n"
                "- severity: one of ['low','medium','high'].\n"
                "- check_type must be one of: 'leave_advance_days', 'benefit_max_amount', 'benefit_requires_receipt', 'benefit_allowed_types'.\n"
                "- params required by check_type:\n"
                "  • leave_advance_days: {request_date_column, start_date_column, min_days_before}\n"
                "  • benefit_max_amount: {amount_column, max_amount}\n"
                "  • benefit_requires_receipt: {receipt_column}\n"
                "  • benefit_allowed_types: {type_column, allowed_types}\n"
                "- rule_code format: 'LEAVE_###' for leave or 'BEN_###' for benefit.\n"
                "Example output: [{\"rule_code\":\"LEAVE_001\",\"description\":\"...\",\"category\":\"leave\",\"severity\":\"medium\",\"check_type\":\"leave_advance_days\",\"params\":{\"request_date_column\":\"request_date\",\"start_date_column\":\"leave_start_date\",\"min_days_before\":3}}]",
            ),
            (
                "human",
                "Policy Text (scope={scope}):\n\n{policy_text}\n\nReturn JSON array only.",
            ),
        ]
    )

    def generate(state: RulesState) -> RulesState:
        msgs = prompt.format_messages(policy_text=state["policy_text"], scope=state["scope"]) 
        res = llm.invoke(msgs)
        return {"raw_output": getattr(res, "content", str(res))}

    def parse(state: RulesState) -> RulesState:
        rules = _clean_and_parse_json(state["raw_output"]) if state.get("raw_output") else []
        return {"rules": rules, "parsed_ok": len(rules) > 0}

    def repair(state: RulesState) -> RulesState:
        from langchain.prompts import ChatPromptTemplate
        repair_instructions = (
            "Your prior output was not a valid JSON array or violated the schema. "
            "Rewrite it as ONLY a JSON array strictly matching the specified keys and check_type parameter requirements. "
            "Do not include explanations or markdown fences."
        )
        repair_prompt = ChatPromptTemplate.from_messages([
            ("system", repair_instructions),
            ("human", "{prior}"),
        ])
        msgs = repair_prompt.format_messages(prior=state.get("raw_output", ""))
        res = _get_llm().invoke(msgs)
        raw2 = getattr(res, "content", str(res))
        rules = _clean_and_parse_json(raw2)
        return {"raw_output": raw2, "rules": rules, "parsed_ok": len(rules) > 0}

    workflow = StateGraph(RulesState)
    workflow.add_node("generate", generate)
    workflow.add_node("parse", parse)
    workflow.add_node("repair", repair)
    workflow.set_entry_point("generate")
    workflow.add_edge("generate", "parse")

    def _cond(state: RulesState):
        return END if state.get("parsed_ok") else "repair"

    workflow.add_conditional_edges("parse", _cond, {"repair": "repair", END: END})
    workflow.add_edge("repair", END)
    graph = workflow.compile()

    final_state = graph.invoke({"policy_text": policy_text, "scope": scope})
    return final_state.get("rules", [])


def explain_violation_with_langchain(payload: Dict[str, Any]) -> str:
    """Generate a concise, clear explanation for a violation using LangChain.

    Expects payload to contain: policy_name, policy_text, scope, rule (with fields),
    evidence, employee_identifier.
    """
    try:
        from langchain.prompts import ChatPromptTemplate
    except Exception as e:
        raise MissingDepsError("LangChain not installed. Install 'langchain'.") from e

    llm = _get_llm()

    # Tighten explanation guidance for consistency and brevity
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a compliance assistant. Explain violations succinctly for HR analysts. "
                "Respond in 1-3 sentences. Be specific (include numbers/thresholds from params). "
                "Do not include JSON or markdown, and do not invent facts beyond the provided evidence and params."
            ),
            (
                "human",
                "Policy: {policy_name}\n"
                "Rule: {rule_code} ({category}, {severity}) - {rule_description}\n"
                "Check Type: {check_type}\n"
                "Params: {params}\n"
                "Employee: {employee_identifier}\n"
                "Evidence: {evidence}\n\n"
                "Policy Text:\n{policy_text}\n\n"
                "Explain why the evidence violates the rule.",
            ),
        ]
    )

    rule = payload.get("rule", {})
    msgs = prompt.format_messages(
        policy_name=payload.get("policy_name", ""),
        policy_text=payload.get("policy_text", ""),
        rule_code=rule.get("rule_code", ""),
        rule_description=rule.get("description", ""),
        category=rule.get("category", ""),
        severity=rule.get("severity", ""),
        check_type=rule.get("check_type", ""),
        params=json.dumps(rule.get("params", {})),
        employee_identifier=payload.get("employee_identifier", ""),
        evidence=payload.get("evidence", ""),
    )
    res = llm.invoke(msgs)
    return getattr(res, "content", str(res)).strip()
