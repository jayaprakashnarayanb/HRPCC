import re
from typing import Any, Dict, List


def _to_number(text: str) -> float:
    # Remove currency symbols and commas, handle simple decimals
    t = text.strip().replace(",", "")
    t = re.sub(r"^[^0-9.-]+", "", t)  # trim non-numeric prefix like $
    try:
        return float(t)
    except Exception:
        return 0.0


def parse_rules_from_text(policy_text: str, scope: str = "both") -> List[Dict[str, Any]]:
    """Parse a constrained set of simple-English policy sentences into rule dicts.

    Supported patterns (case-insensitive):
    - Leave (advance notice):
      "Annual leave must be requested at least N days before the leave start date."
    - Benefits (max amount):
      "Claims above $X are not allowed (without prior approval)."
      or "Claim amount must be <= X."
    - Benefits (receipt required):
      "A receipt must be attached for all claims." / "All benefit claims require a receipt."
    - Benefits (allowed types):
      "Allowed claim types include A, B, and C." / "Allowed claim types are A, B, C."

    Returns a list of rule dicts matching the app.models.Rule structure.
    """
    text = policy_text.strip()
    rules: List[Dict[str, Any]] = []

    want_leave = scope in ("both", "leave")
    want_benefit = scope in ("both", "benefit")

    # Normalize whitespace for simpler regex
    normalized = re.sub(r"\s+", " ", text)

    # --- Leave: advance notice ---
    if want_leave:
        m = re.search(
            r"\b(?:annual\s+)?leave\s+must\s+be\s+requested\s+at\s+least\s+(\d+)\s+days\s+before\s+(?:the\s+)?(?:leave\s+)?start\s+date\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if m:
            days = int(m.group(1))
            rules.append(
                {
                    "rule_code": f"LEAVE_{len([r for r in rules if r.get('category')=='leave'])+1:03d}",
                    "description": f"Annual leave must be requested at least {days} days before the start date.",
                    "category": "leave",
                    "severity": "medium",
                    "check_type": "leave_advance_days",
                    "params": {
                        "request_date_column": "request_date",
                        "start_date_column": "leave_start_date",
                        "min_days_before": days,
                    },
                }
            )

    # --- Benefit: max amount ---
    if want_benefit:
        m1 = re.search(
            r"\bclaims?\s+(?:above|over|greater\s+than)\s+([$€£]?\s*[0-9][0-9,]*\.?[0-9]*)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        m2 = re.search(
            r"\bclaim\s+amount\s+must\s+be\s*(?:<=|less\s+than\s+or\s+equal\s+to)\s+([$€£]?\s*[0-9][0-9,]*\.?[0-9]*)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if m1 or m2:
            amt = _to_number((m1 or m2).group(1))
            rules.append(
                {
                    "rule_code": f"BEN_{len([r for r in rules if r.get('category')=='benefit'])+1:03d}",
                    "description": f"Claim amount must be <= {int(amt) if amt.is_integer() else amt}.",
                    "category": "benefit",
                    "severity": "high",
                    "check_type": "benefit_max_amount",
                    "params": {"amount_column": "claim_amount", "max_amount": amt},
                }
            )

        # --- Benefit: receipt required ---
        if re.search(
            r"\b(?:a\s+)?receipt\s+must\s+be\s+attached\s+for\s+all\s+claims\b|\ball\s+benefit\s+claims\s+require\s+a\s+receipt\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            rules.append(
                {
                    "rule_code": f"BEN_{len([r for r in rules if r.get('category')=='benefit'])+1:03d}",
                    "description": "All benefit claims require a receipt.",
                    "category": "benefit",
                    "severity": "medium",
                    "check_type": "benefit_requires_receipt",
                    "params": {"receipt_column": "receipt_attached"},
                }
            )

        # --- Benefit: allowed types ---
        m3 = re.search(
            r"\ballowed\s+claim\s+types\s+(?:include|are)\s+([^\.]+)\.",
            normalized,
            flags=re.IGNORECASE,
        )
        if m3:
            raw = m3.group(1)
            # Split on commas and 'and', then strip any leading conjunctions
            parts = re.split(r"\s*,\s*|\s+and\s+|\s+or\s+", raw.strip())
            cleaned: List[str] = []
            for p in parts:
                t = p.strip().lower()
                if not t:
                    continue
                t = re.sub(r"^(and|or)\s+", "", t)
                cleaned.append(t)
            types = [t for t in cleaned if t]
            if types:
                rules.append(
                    {
                        "rule_code": f"BEN_{len([r for r in rules if r.get('category')=='benefit'])+1:03d}",
                        "description": f"Allowed claim types are {', '.join(types)}.",
                        "category": "benefit",
                        "severity": "low",
                        "check_type": "benefit_allowed_types",
                        "params": {"type_column": "claim_type", "allowed_types": types},
                    }
                )

    return rules
