import os
from app.app import create_app
from app.db import get_db
from app.models import Policy, Rule, Dataset, Violation
from app.compliance import run_compliance


def main():
    app = create_app()
    client = app.test_client()

    # 1) Seed demo data (policies, datasets, and initial violations)
    client.get("/seed")

    # 2) Ensure the simple-parse policy exists
    db = next(get_db())
    name = "Smoke Simple Parse Policy"
    policy = db.query(Policy).filter(Policy.name == name).first()

    if not policy:
        # Create policy from sample text
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        sample_policy_path = os.path.join(repo_root, "sample_data", "sample_policy.txt")
        with open(sample_policy_path, "r", encoding="utf-8") as f:
            sample_text = f.read()
        client.post(
            "/policies",
            data={"name": name, "scope": "both", "raw_text": sample_text},
            follow_redirects=True,
        )
        policy = db.query(Policy).filter(Policy.name == name).first()

    # 3) Ensure rules exist for this policy via simple parser
    rules_count = db.query(Rule).filter(Rule.policy_id == policy.id).count()
    if rules_count == 0:
        client.post(f"/policies/{policy.id}/extract_rules_simple", follow_redirects=True)
        rules_count = db.query(Rule).filter(Rule.policy_id == policy.id).count()

    print(f"Policy: {policy.name} (id={policy.id}), rules={rules_count}")

    # 4) Find sample datasets (leave and benefit)
    datasets = db.query(Dataset).all()
    targets = [ds for ds in datasets if ds.dataset_type in ("leave", "benefit")]
    if not targets:
        print("No datasets found; seed may have failed.")
        return

    # 5) Clear old violations for this policy and run compliance
    total = 0
    for ds in targets:
        db.query(Violation).filter(
            Violation.policy_id == policy.id, Violation.dataset_id == ds.id
        ).delete()
        vs = run_compliance(db, policy.id, ds.id)
        print(f"Dataset: {ds.name} (type={ds.dataset_type}) -> violations={len(vs)}")
        for v in vs[:5]:
            print({
                "employee": v.employee_identifier,
                "rule_id": v.rule_id,
                "risk": v.risk,
                "evidence": (v.evidence[:100] + "...") if v.evidence and len(v.evidence) > 100 else v.evidence,
            })
        total += len(vs)

    print(f"Total violations: {total}")


if __name__ == "__main__":
    main()

