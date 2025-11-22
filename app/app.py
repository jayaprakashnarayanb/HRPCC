# app/app.py
import os
from flask import (
    Flask, request, render_template, redirect,
    url_for, jsonify, flash
)
from werkzeug.utils import secure_filename
from sqlalchemy.orm import Session
import requests

from .db import Base, engine, get_db
from .models import Policy, Rule, Dataset, Violation
from .compliance import run_compliance
from .policy_parser import parse_rules_from_text

def _upload_dir_default() -> str:
    # Prefer env var, then Render Disk at /data, then local folder
    env_dir = os.getenv("UPLOAD_DIR")
    if env_dir:
        return env_dir
    if os.path.isdir("/data"):
        return "/data/uploads"
    return "uploads"

UPLOAD_DIR = _upload_dir_default()


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Create DB tables
    Base.metadata.create_all(bind=engine)

    # LLM configuration via environment (Gemini):
    # - GOOGLE_API_KEY (required)
    # - GEMINI_MODEL (optional, default: gemini-1.5-flash)

    # ---------- ROUTES ----------

    @app.route("/")
    def index():
        db = next(get_db())
        policies = db.query(Policy).all()
        datasets = db.query(Dataset).all()
        violations = db.query(Violation).all()
        return render_template(
            "index.html",
            policies=policies,
            datasets=datasets,
            violations_count=len(violations),
        )

    # ---- Settings ----
    @app.route("/settings", methods=["GET"])
    def settings_page():
        openai_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        has_api_key = bool(os.getenv("GOOGLE_API_KEY"))
        # Check package availability
        try:
            import langchain  # noqa: F401
            import langgraph  # noqa: F401
            from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: F401
            pkgs_ok = True
        except Exception:
            pkgs_ok = False
        return render_template(
            "settings.html",
            model=openai_model,
            has_api_key=has_api_key,
            pkgs_ok=pkgs_ok,
        )

    @app.route("/settings/test", methods=["POST"])
    def settings_test():
        try:
            from .ai import _get_llm
            llm = _get_llm()
            res = llm.invoke("Reply with OK")
            content = getattr(res, "content", str(res))
            flash(f"LLM test succeeded: {content[:120]}...", "success")
        except Exception as e:
            flash(f"LLM test failed: {e}", "error")
        return redirect(url_for("settings_page"))

    # ---- Policies ----
    @app.route("/policies", methods=["GET", "POST"])
    def policies():
        db = next(get_db())
        if request.method == "POST":
            name = request.form.get("name")
            raw_text = request.form.get("raw_text")
            scope = request.form.get("scope", "both")  # leave/benefit/both
            if not name or not raw_text:
                flash("Name and text are required", "error")
            else:
                p = Policy(name=name, raw_text=raw_text, scope=scope)
                db.add(p)
                db.commit()
                flash("Policy created", "success")
                return redirect(url_for("policies"))

        policies = db.query(Policy).all()
        return render_template("policies.html", policies=policies)

    @app.route("/policies/<int:policy_id>/extract_rules", methods=["POST"])
    def extract_rules(policy_id):
        db = next(get_db())
        policy = db.query(Policy).filter(Policy.id == policy_id).first()
        if not policy:
            return "Policy not found", 404

        try:
            from .ai import extract_rules_with_langgraph
            rules_json = extract_rules_with_langgraph(policy.raw_text, policy.scope)
        except Exception as e:
            flash(f"Rule extraction error: {e}", "error")
            return redirect(url_for("policies"))

        for r in rules_json:
            rule = Rule(
                policy_id=policy.id,
                rule_code=r.get("rule_id") or r.get("rule_code"),
                description=r.get("description", ""),
                category=r.get("category", "leave"),  # leave or benefit
                severity=r.get("severity", "medium"),
                check_type=r.get("check_type", ""),
                params=r.get("params", {}),
            )
            db.add(rule)
        db.commit()
        flash(f"Extracted {len(rules_json)} rules from policy", "success")
        return redirect(url_for("policies"))

    @app.route("/policies/<int:policy_id>/extract_rules_simple", methods=["POST"])
    def extract_rules_simple(policy_id):
        db = next(get_db())
        policy = db.query(Policy).filter(Policy.id == policy_id).first()
        if not policy:
            return "Policy not found", 404

        rules_json = parse_rules_from_text(policy.raw_text or "", policy.scope or "both")

        if not rules_json:
            flash("No rules recognized. Please follow the simple-English patterns documented in README.", "error")
            return redirect(url_for("policies"))

        for r in rules_json:
            rule = Rule(
                policy_id=policy.id,
                rule_code=r.get("rule_id") or r.get("rule_code"),
                description=r.get("description", ""),
                category=r.get("category", "leave"),
                severity=r.get("severity", "medium"),
                check_type=r.get("check_type", ""),
                params=r.get("params", {}),
            )
            db.add(rule)
        db.commit()
        flash(f"Extracted {len(rules_json)} rules from policy (simple parser)", "success")
        return redirect(url_for("policies"))

    @app.route("/policies/<int:policy_id>/extract_rules_preview", methods=["POST"])
    def extract_rules_preview(policy_id):
        db = next(get_db())
        policy = db.query(Policy).filter(Policy.id == policy_id).first()
        if not policy:
            return "Policy not found", 404
        try:
            from .ai import extract_rules_with_langgraph
            rules_json = extract_rules_with_langgraph(policy.raw_text, policy.scope)
        except Exception as e:
            flash(f"Rule extraction error: {e}", "error")
            return redirect(url_for("policies"))
        return render_template(
            "rules_preview.html",
            policy=policy,
            rules_json=rules_json,
            rules_json_str=json.dumps(rules_json, indent=2, ensure_ascii=False),
        )

    @app.route("/policies/<int:policy_id>/save_rules", methods=["POST"])
    def save_rules(policy_id):
        db = next(get_db())
        policy = db.query(Policy).filter(Policy.id == policy_id).first()
        if not policy:
            return "Policy not found", 404
        try:
            payload = request.form.get("rules_json") or "[]"
            rules_json = json.loads(payload)
            if not isinstance(rules_json, list):
                raise ValueError("rules_json must be a JSON array")
        except Exception as e:
            flash(f"Invalid rules JSON: {e}", "error")
            return redirect(url_for("policies"))

        count = 0
        for r in rules_json:
            rule = Rule(
                policy_id=policy.id,
                rule_code=r.get("rule_id") or r.get("rule_code"),
                description=r.get("description", ""),
                category=r.get("category", "leave"),
                severity=r.get("severity", "medium"),
                check_type=r.get("check_type", ""),
                params=r.get("params", {}),
            )
            db.add(rule)
            count += 1
        db.commit()
        flash(f"Saved {count} rules to policy {policy.name}", "success")
        return redirect(url_for("view_rules", policy_id=policy.id))

    @app.route("/policies/<int:policy_id>/rules")
    def view_rules(policy_id):
        db = next(get_db())
        policy = db.query(Policy).filter(Policy.id == policy_id).first()
        if not policy:
            return "Policy not found", 404
        rules = db.query(Rule).filter(Rule.policy_id == policy_id).all()
        return render_template("rules.html", policy=policy, rules=rules)

    # ---- Datasets ----
    @app.route("/datasets", methods=["GET", "POST"])
    def datasets():
        db = next(get_db())
        if request.method == "POST":
            name = request.form.get("name")
            description = request.form.get("description")
            dataset_type = request.form.get("dataset_type")  # leave/benefit
            file = request.files.get("file")

            if not name or not file or dataset_type not in ("leave", "benefit"):
                flash("Name, file and dataset type are required", "error")
            else:
                filename = secure_filename(file.filename)
                path = os.path.join(UPLOAD_DIR, filename)
                file.save(path)

                d = Dataset(
                    name=name,
                    description=description,
                    dataset_type=dataset_type,
                    file_path=path,
                )
                db.add(d)
                db.commit()
                flash("Dataset uploaded", "success")
                return redirect(url_for("datasets"))

        datasets = db.query(Dataset).all()
        policies = db.query(Policy).all()
        return render_template(
            "datasets.html", datasets=datasets, policies=policies
        )

    # ---- Compliance run ----
    @app.route("/compliance/run", methods=["POST"])
    def run_compliance_route():
        db_session = next(get_db())
        policy_id = int(request.form.get("policy_id"))
        dataset_id = int(request.form.get("dataset_id"))
        explain = request.form.get("explain") == "on"

        # Clear previous violations for this pair (optional)
        db_session.query(Violation).filter(
            Violation.policy_id == policy_id,
            Violation.dataset_id == dataset_id,
        ).delete()

        violations = run_compliance(db_session, policy_id, dataset_id)

        # Optionally generate explanations via LangChain
        if explain and violations:
            for v in violations:
                rule: Rule = (
                    db_session.query(Rule).filter(Rule.id == v.rule_id).first()
                )
                policy: Policy = (
                    db_session.query(Policy)
                    .filter(Policy.id == v.policy_id)
                    .first()
                )
                payload = {
                    "violation_id": v.id,
                    "policy_name": policy.name if policy else "",
                    "policy_text": policy.raw_text if policy else "",
                    "scope": rule.category if rule else "",
                    "rule": {
                        "rule_code": rule.rule_code,
                        "description": rule.description,
                        "category": rule.category,
                        "severity": rule.severity,
                        "check_type": rule.check_type,
                        "params": rule.params,
                    },
                    "evidence": v.evidence,
                    "employee_identifier": v.employee_identifier,
                }
                try:
                    from .ai import explain_violation_with_langchain
                    explanation = explain_violation_with_langchain(payload)
                    if explanation:
                        v.explanation = explanation
                        db_session.add(v)
                except Exception as e:
                    print(f"explanation error: {e}")

            db_session.commit()

        flash(
            f"Compliance run complete. Found {len(violations)} potential violations.",
            "success",
        )
        return redirect(url_for("violations"))

    # ---- Violations ----
    @app.route("/violations")
    def violations():
        db = next(get_db())
        violations = db.query(Violation).all()
        return render_template("violations.html", violations=violations)

    # Simple JSON API for violations (optional)
    @app.route("/api/violations")
    def violations_api():
        db = next(get_db())
        vs = db.query(Violation).all()
        return jsonify(
            [
                {
                    "id": v.id,
                    "policy_id": v.policy_id,
                    "rule_id": v.rule_id,
                    "dataset_id": v.dataset_id,
                    "employee_identifier": v.employee_identifier,
                    "evidence": v.evidence,
                    "risk": v.risk,
                    "explanation": v.explanation,
                }
                for v in vs
            ]
        )

    # ---- Seed demo data ----
    @app.route("/seed")
    def seed():
        db = next(get_db())

        # Load sample policy text
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        sample_dir = os.path.join(repo_root, "sample_data")
        policy_path = os.path.join(sample_dir, "sample_policy.txt")
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                policy_text = f.read()
        except Exception:
            policy_text = (
                "Annual leave must be requested at least 3 days in advance.\n"
                "Claims above $1,000 are not allowed without prior approval.\n"
                "A receipt must be attached for all claims.\n"
                "Allowed claim types include medical, transport, and meal.\n"
            )

        # Ensure a policy exists
        policy = db.query(Policy).filter(Policy.name == "Sample HR Policy").first()
        created = {"policy": False, "rules": 0, "datasets": 0, "violations": 0}
        if not policy:
            policy = Policy(name="Sample HR Policy", raw_text=policy_text, scope="both")
            db.add(policy)
            db.commit()
            db.refresh(policy)
            created["policy"] = True

        # Seed rules if none exist for this policy
        existing_rules = db.query(Rule).filter(Rule.policy_id == policy.id).count()
        if existing_rules == 0:
            rule_defs = [
                {
                    "rule_code": "LEAVE_001",
                    "description": "Annual leave must be requested at least 3 days before the start date.",
                    "category": "leave",
                    "severity": "medium",
                    "check_type": "leave_advance_days",
                    "params": {
                        "request_date_column": "request_date",
                        "start_date_column": "leave_start_date",
                        "min_days_before": 3,
                    },
                },
                {
                    "rule_code": "BEN_001",
                    "description": "Claim amount must be <= 1000.",
                    "category": "benefit",
                    "severity": "high",
                    "check_type": "benefit_max_amount",
                    "params": {"amount_column": "claim_amount", "max_amount": 1000},
                },
                {
                    "rule_code": "BEN_002",
                    "description": "All benefit claims require a receipt.",
                    "category": "benefit",
                    "severity": "medium",
                    "check_type": "benefit_requires_receipt",
                    "params": {"receipt_column": "receipt_attached"},
                },
                {
                    "rule_code": "BEN_003",
                    "description": "Allowed claim types are medical, transport, and meal.",
                    "category": "benefit",
                    "severity": "low",
                    "check_type": "benefit_allowed_types",
                    "params": {
                        "type_column": "claim_type",
                        "allowed_types": ["medical", "transport", "meal"],
                    },
                },
            ]
            for r in rule_defs:
                db.add(
                    Rule(
                        policy_id=policy.id,
                        rule_code=r["rule_code"],
                        description=r["description"],
                        category=r["category"],
                        severity=r["severity"],
                        check_type=r["check_type"],
                        params=r["params"],
                    )
                )
            db.commit()
            created["rules"] = len(rule_defs)

        # Seed datasets (point to sample CSVs)
        leave_csv = os.path.join(sample_dir, "leave_requests.csv")
        benefit_csv = os.path.join(sample_dir, "benefit_claims.csv")

        def ensure_dataset(name, dtype, path, desc):
            ds = (
                db.query(Dataset)
                .filter(Dataset.name == name, Dataset.dataset_type == dtype)
                .first()
            )
            if not ds and os.path.exists(path):
                ds = Dataset(
                    name=name,
                    description=desc,
                    dataset_type=dtype,
                    file_path=os.path.abspath(path),
                )
                db.add(ds)
                db.commit()
                db.refresh(ds)
                return ds, True
            return ds, False

        leave_ds, created_leave = ensure_dataset(
            "Sample Leave Requests", "leave", leave_csv, "Demo leave requests"
        )
        benefit_ds, created_ben = ensure_dataset(
            "Sample Benefit Claims", "benefit", benefit_csv, "Demo benefit claims"
        )
        created["datasets"] = int(created_leave) + int(created_ben)

        # Run compliance for available datasets
        total_violations = 0
        for ds in (leave_ds, benefit_ds):
            if not ds:
                continue
            db.query(Violation).filter(
                Violation.policy_id == policy.id, Violation.dataset_id == ds.id
            ).delete()
            vs = run_compliance(db, policy.id, ds.id)
            total_violations += len(vs)
        created["violations"] = total_violations

        flash(
            f"Seeded: policy={'yes' if created['policy'] else 'no'}, "
            f"rules={created['rules']}, datasets={created['datasets']}, "
            f"violations={created['violations']}",
            "success",
        )
        return redirect(url_for("index"))

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
