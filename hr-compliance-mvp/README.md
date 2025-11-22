# HR Compliance MVP (Leave & Benefits)

A minimal Flask + SQLAlchemy app to manage HR policies, extract machine‑checkable rules using LangChain/LangGraph, upload datasets (leave requests and benefit claims), run compliance checks, and list potential violations.

## Features
- Policies CRUD (scope: leave, benefit, or both)
- Rule extraction via LangChain + LangGraph
- CSV dataset upload (leave/benefit)
- Compliance engine for:
  - leave_advance_days
  - benefit_max_amount
  - benefit_requires_receipt
  - benefit_allowed_types
- Optional violation explanations via LangChain
 - Settings page to test LLM connectivity and view model
 - Rule Extraction Preview before saving to DB
 - Simple parser to extract rules from plain English (no LLM)

## Quickstart (Local)
1. Python 3.10+
2. `cd hr-compliance-mvp`
3. `python -m venv .venv && source .venv/bin/activate`
4. `pip install -r requirements.txt`
5. `export FLASK_SECRET_KEY=dev` (optional)
6. Set Gemini credentials for LangChain:
   - `export GOOGLE_API_KEY=...` (required)
   - `export GEMINI_MODEL=gemini-1.5-flash` (optional)
7. Run: `python -m flask --app app.app run --debug`

Open http://127.0.0.1:5000

### Seed demo data
- Visit `http://127.0.0.1:5000/seed` once to create:
  - A sample policy and 4 rules (leave + benefits)
  - Two datasets pointing to files in `sample_data/`
  - Runs a compliance check to populate violations

## Sample Data
- `sample_data/sample_policy.txt`
- `sample_data/leave_requests.csv`
- `sample_data/benefit_claims.csv`

Upload the CSVs on the Datasets page. Add a policy (e.g., paste sample_policy.txt), then extract rules (requires Gemini credentials set for LangChain) or edit rules directly in DB.

### New UI actions
- Settings: check LLM setup and run a quick connectivity test.
- Policies: use “Preview Extraction” to inspect the JSON before saving; use “Extract & Save” to persist rules immediately.
- Policies: use “Extract (Simple Parse)” to convert supported plain-English sentences into rules deterministically (no LLM required).

## Simple-English Policy Format (Deterministic)
You can write policies in straightforward sentences that the app can parse without any AI. Supported patterns are case-insensitive and should end in periods:

- Leave (advance notice):
  - "Annual leave must be requested at least N days before the leave start date."
  - Example: "Annual leave must be requested at least 3 days before the leave start date."

- Benefits (max amount):
  - "Claims above $X are not allowed (without prior approval)."
  - or "Claim amount must be <= X."
  - Example: "Claims above $1,000 are not allowed without prior approval."

- Benefits (receipt required):
  - "A receipt must be attached for all claims."
  - or "All benefit claims require a receipt."

- Benefits (allowed claim types):
  - "Allowed claim types include A, B, and C."
  - or "Allowed claim types are A, B, C."

Column assumptions used by the compliance engine:
- Leave: `request_date`, `leave_start_date`
- Benefits: `claim_amount`, `receipt_attached`, `claim_type`

If your CSVs use different column names, either adapt them to match or use the LLM-based extractor and edit the parameters in the preview before saving.

## Deploy (Render)
- Ensure repository contains this folder at repo root or set Render root.
- Render blueprint `render.yaml` is included; it runs `gunicorn app:app` bound to `$PORT`.
- A persistent Disk is configured and mounted at `/data`.
- The app automatically uses `/data` for the SQLite DB (`/data/hr_compliance.db`) and uploads (`/data/uploads`).
- Add env vars in the Render dashboard as needed.

### Customization
- Database: Set `DATABASE_URL` to override (e.g., a managed Postgres URL). If unset, the app uses `/data/hr_compliance.db` when `/data` exists, otherwise `hr_compliance.db` in the project root.
- Uploads: Set `UPLOAD_DIR` to override. If unset, the app uses `/data/uploads` when `/data` exists, otherwise `uploads/` in the project root.

## Docker
Build and run with Docker:
- `cd hr-compliance-mvp`
- `docker build -t hr-compliance-mvp .`
- `docker run --rm -p 8000:8000 -e FLASK_SECRET_KEY=dev hr-compliance-mvp`

Open http://localhost:8000 then hit `/seed` once for demo data.

### Docker Compose
- `cd hr-compliance-mvp`
- `docker compose up --build`
- App: http://localhost:8000 (seed at `/seed`)

Ensure the `GOOGLE_API_KEY` is set in your environment or compose file for rule extraction and explanations.


## Notes
- SQLite DB file `hr_compliance.db` is created in the working directory.
- Uploads are stored under `uploads/` at runtime.

## Troubleshooting
- 401: API keys are not supported by this API
  - Cause: Some environments expose Google Application Default Credentials (ADC), causing the client to attempt OAuth2 instead of API key auth, which can trigger a 401 with this message.
  - Fix: This app now explicitly passes `GOOGLE_API_KEY` to the Gemini client. Ensure `GOOGLE_API_KEY` is set and valid. If your organization forbids API keys and requires OAuth/Service Account, you’ll need to integrate OAuth2 credentials instead of API keys (not covered by this MVP).
 - 404: models/gemini-1.5-flash-latest is not found for API version v1beta
   - Cause: Some library versions or environments use the v1beta API where the "-latest" alias is not available or not supported for `generateContent`.
   - Fix: Use a concrete model name without the `-latest` suffix (e.g., `gemini-1.5-flash` or `gemini-1.5-pro`). The app defaults to `gemini-1.5-flash` and strips `-latest` automatically if present.
