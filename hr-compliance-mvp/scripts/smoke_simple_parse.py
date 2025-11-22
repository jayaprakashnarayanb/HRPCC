import os
from app.app import create_app
from app.db import get_db
from app.models import Policy, Rule


def main():
    app = create_app()
    client = app.test_client()

    # 1) Seed demo data (creates DB/tables and sample policy/datasets)
    client.get("/seed")

    # 2) Create a new policy using the sample policy text
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sample_policy_path = os.path.join(repo_root, "sample_data", "sample_policy.txt")
    with open(sample_policy_path, "r", encoding="utf-8") as f:
        sample_text = f.read()

    policy_name = "Smoke Simple Parse Policy"
    client.post(
        "/policies",
        data={
            "name": policy_name,
            "scope": "both",
            "raw_text": sample_text,
        },
        follow_redirects=True,
    )

    # 3) Get the policy id from the DB
    db = next(get_db())
    policy = db.query(Policy).filter(Policy.name == policy_name).first()
    assert policy, "Policy was not created"

    # 4) Run the simple parser extraction route
    client.post(f"/policies/{policy.id}/extract_rules_simple", follow_redirects=True)

    # 5) Verify rules saved
    rules = db.query(Rule).filter(Rule.policy_id == policy.id).all()
    print(f"Policy ID: {policy.id}, Rules created: {len(rules)}")
    for r in rules:
        print({
            "rule_code": r.rule_code,
            "category": r.category,
            "check_type": r.check_type,
            "params": r.params,
        })


if __name__ == "__main__":
    main()

