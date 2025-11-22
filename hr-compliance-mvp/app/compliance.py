# app/compliance.py
import csv
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
from .models import Rule, Dataset, Violation


def parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def apply_rule_to_row(rule: Rule, row: dict, dataset_type: str):
    """
    Returns (is_violation: bool, evidence: str)
    """
    ct = rule.check_type

    # ---------- LEAVE RULES ----------
    if dataset_type == "leave":
        # leave_advance_days: request must be N days before leave_start
        if ct == "leave_advance_days":
            request_col = rule.params.get("request_date_column", "request_date")
            start_col = rule.params.get("start_date_column", "leave_start_date")
            min_days = rule.params.get("min_days_before", 3)

            req_val = row.get(request_col)
            start_val = row.get(start_col)
            d_req = parse_date(req_val)
            d_start = parse_date(start_val)

            if not d_req or not d_start:
                return False, "Missing or invalid dates"

            diff = (d_start - d_req).days
            if diff < min_days:
                return True, (
                    f"Leave requested {diff} days before start; "
                    f"policy requires at least {min_days} days."
                )
            return False, ""

    # ---------- BENEFIT CLAIM RULES ----------
    if dataset_type == "benefit":
        # benefit_max_amount: claim_amount must be <= max_amount
        if ct == "benefit_max_amount":
            amount_col = rule.params.get("amount_column", "claim_amount")
            max_amount = rule.params.get("max_amount", 1000.0)
            try:
                amount = float(row.get(amount_col, 0))
            except ValueError:
                return False, "Invalid claim amount"
            if amount > max_amount:
                return True, (
                    f"Claim amount {amount} exceeds max allowed {max_amount}."
                )
            return False, ""

        # benefit_requires_receipt: receipt flag must be true-ish
        if ct == "benefit_requires_receipt":
            receipt_col = rule.params.get("receipt_column", "receipt_attached")
            val = str(row.get(receipt_col, "")).strip().lower()
            has_receipt = val in ("yes", "true", "1", "y")
            if not has_receipt:
                return True, (
                    f"Receipt is required but '{receipt_col}' is '{val}'."
                )
            return False, ""

        # benefit_allowed_types: claim_type must be in allowed list
        if ct == "benefit_allowed_types":
            type_col = rule.params.get("type_column", "claim_type")
            allowed = [t.lower() for t in rule.params.get("allowed_types", [])]
            v = str(row.get(type_col, "")).strip().lower()
            if allowed and v not in allowed:
                return True, (
                    f"Claim type '{v}' is not in allowed types: "
                    f"{', '.join(allowed)}"
                )
            return False, ""

    # Unknown / unsupported rule for this dataset
    return False, "Rule type not applicable or not implemented"


def run_compliance(db: Session, policy_id: int, dataset_id: int) -> List[Violation]:
    dataset: Dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise ValueError("Dataset not found")

    dataset_type = dataset.dataset_type  # "leave" or "benefit"

    rules: List[Rule] = (
        db.query(Rule)
        .filter(Rule.policy_id == policy_id, Rule.category == dataset_type)
        .all()
    )

    if not rules:
        return []

    violations_created: List[Violation] = []

    with open(dataset.file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            employee_id = (
                row.get("employee_id")
                or row.get("employee")
                or row.get("emp_id")
                or "UNKNOWN"
            )
            for rule in rules:
                is_violation, evidence = apply_rule_to_row(rule, row, dataset_type)
                if is_violation:
                    v = Violation(
                        policy_id=policy_id,
                        rule_id=rule.id,
                        dataset_id=dataset_id,
                        employee_identifier=employee_id,
                        evidence=evidence,
                        risk=rule.severity or "medium",
                    )
                    db.add(v)
                    violations_created.append(v)

    db.commit()
    for v in violations_created:
        db.refresh(v)
    return violations_created

