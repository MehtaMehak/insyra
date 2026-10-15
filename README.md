# Insyra: Product Feedback, Approval Workflow, and n8n Automation

Insyra is a local full-stack prototype for analyzing public Groww Android app
reviews, generating an approved Product Pulse and fee explainer, and
approval-gating any external documentation/draft creation.

The backend is Python/FastAPI and the frontend is React/Vite. Generated reports
and review analysis are stored locally. Approved actions are recorded in an
approval ledger with immutable snapshots and duplicate protection.

## Features

- Collects and stores Groww Android app reviews.
- Uses a deliberately selected 300-review sample for AI/tagged analysis.
- Generates a Weekly Product Pulse with top themes, verified customer quotes,
  fee-confusion observations, and recommended actions.
- Generates a Groww fee explainer from official Groww documentation.
- Approval/rejection workflow with immutable request snapshots.
- Approved requests execute only after human approval.
- Supports `local` and `mcp_mock` provider modes for notes and Gmail drafts.
- Optionally notifies an authenticated n8n webhook after both provider actions
  succeed.
- Records audit history in `backend/data/approvals.json`. The ledger file is
  local runtime data and should not be committed.

## Dataset

- `backend/data/groww_reviews.csv`: 12,680 public Groww Android app reviews.
- `backend/data/analysis_sample.csv`: 300 deliberately selected review sample.
- The 300-review sample is intentionally not representative of all 12,680
  reviews. It is used to surface candidate themes and quoted feedback, and
  fee-related language is treated as keyword candidates, not confirmed
  complaints.

## Analysis and Reports

The Top 3 themes in the Weekly Product Pulse are:

1. Hidden brokerage and transaction fees
2. Unclear fee disclosure
3. Customer support inadequacy

Verified customer quotes are preserved with source review links in
`backend/data/weekly_pulse.md`. The Weekly Product Pulse also notes that
fee-related keyword candidates appeared in 206 of 300 sampled reviews, with
high severity. These are keyword candidates, not confirmed complaints.

The fee explainer is based on official Groww pricing/help documentation
accessed on 2026-10-14. Its official sources are:

- Brokerage Charges & Pricing | Groww: https://groww.in/pricing/
- What are intraday charges?: https://groww.in/help/stocks,-f&o,-ipo-&-mtf/sx-pricing/what-are-intraday-charges
- What fees does Groww charge?: https://groww.in/help/payments-&-withdrawals/payments-charges/what-fees-does-groww-charge--58

## Architecture

- `backend/` - FastAPI service, report generation, approval ledger, providers,
  tests, and data files.
- `frontend/` - React/Vite dashboard, Weekly Product Pulse view, CSV upload,
  and approvals UI.
- `submission-evidence/` - screenshot evidence files.
- `backend/scripts/` - review collection and Groq diagnostic scripts.

Important backend endpoints:

- `GET /` - service status
- `GET /health`
- `GET /api/insights`
- `GET /api/weekly-pulse`
- `GET /api/fee-explainer`
- `GET /api/approvals`
- `POST /api/approvals`
- `POST /api/approvals/{request_id}/approve`
- `POST /api/approvals/{request_id}/reject`
- `POST /api/reviews/upload`

## Prerequisites

- Windows PowerShell
- Python virtual environment with the dependencies used by the project
- Node.js and npm for the frontend

## Setup

From the project root:

```powershell
cd C:\Users\ACER\Documents\insyra\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`backend/requirements.txt` currently lists `mcp==2.3.0`; standard FastAPI
runtime dependencies are expected in the environment.

Frontend dependencies:

```powershell
cd C:\Users\ACER\Documents\insyra\frontend
npm install
```

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill values locally. Never
commit `.env` or webhook metadata files.

Backend variables:

```dotenv
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com
GROQ_TIMEOUT_SECONDS=30
GROQ_MAX_RETRIES=2
GROQ_TEMPERATURE=0.2
GROQ_MAX_TOKENS=1024
APPROVAL_PROVIDER_MODE=local
N8N_WEBHOOK_URL=https://your-n8n-host/webhook/your-path
N8N_WEBHOOK_TOKEN=your-n8n-token
```

Allowed `APPROVAL_PROVIDER_MODE` values:

- `local` - local Markdown notes and mock Gmail draft files
- `mcp_mock` - local stdio MCP mock server, restricted to two allowlisted tools

## Run Locally

Start the backend:

```powershell
cd C:\Users\ACER\Documents\insyra\backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8001
```

Start the frontend in another terminal:

```powershell
cd C:\Users\ACER\Documents\insyra\frontend
npm run dev
```

The frontend expects the backend API at `http://127.0.0.1:8001`. Vite usually
serves the frontend at `http://localhost:5173`.

## Approval Workflow

1. Create a request with an immutable snapshot of the current reports.
2. The request starts as `pending`.
3. Approve or reject the pending request.
4. Approval executes providers only once.
5. Re-running execution skips provider actions already marked `succeeded`.
6. Re-approving an already decided request returns a conflict/error.

Local mode writes a Markdown note under
`backend/data/approved_notes/` and a mock Gmail draft JSON file. No email is
sent.

`mcp_mock` mode uses `backend/mcp_test_server.py` through the MCP client with
an allowlist of exactly two tools:

- `create_or_update_google_doc`
- `create_gmail_draft`

It does not send email or call unlisted tools.

## n8n Integration

After approval, if both existing provider actions succeed, Insyra can POST a
plain-text payload to a configured n8n webhook:

```json
{
  "approval_id": "...",
  "document_text": "...",
  "email_subject": "...",
  "email_body": "..."
}
```

The request uses the `X-Insyra-Token` header. n8n is responsible for any
Google Docs/Gmail draft creation. The Insyra application does not send email.
If `N8N_WEBHOOK_URL` or `N8N_WEBHOOK_TOKEN` is missing, the webhook action is
marked skipped and existing approval/provider behavior is not broken.

Webhook authentication requires both variables:

```dotenv
N8N_WEBHOOK_URL=https://your-n8n-host/webhook/your-path
N8N_WEBHOOK_TOKEN=your-n8n-token
```

The n8n workflow and Google nodes are external configuration, not MCP tools.

## Tests

Backend:

```powershell
cd C:\Users\ACER\Documents\insyra\backend
.\.venv\Scripts\Activate.ps1
python -m unittest discover
```

Frontend lint:

```powershell
cd C:\Users\ACER\Documents\insyra\frontend
npm run lint
```

## Milestone 5 Deliverables

- Project code in `backend/` and `frontend/`
- Groww review dataset and 300-review analysis sample
- `backend/data/weekly_pulse.md`
- `backend/data/fee_explainer.md` and `backend/data/fee_explainer.json`
- Approval and rejection workflow implementation
- Approval screenshots in `submission-evidence/`
- n8n webhook authentication configuration
- This README and `backend/.env.example`

Submission evidence files currently included:

- `Screenshot 2026-10-15 155843.png`
- `Screenshot 2026-10-15 155857.png`
- `Screenshot 2026-10-15 155908.png`

## Limitations

- The 300-review sample is deliberately selected and is not representative of
  all 12,680 reviews.
- Fee-related review language is treated as keyword candidates, not confirmed
  complaints.
- Official fee facts should be rechecked before customer-facing use because
  Groww pricing may change.
- This prototype is described as a local project; no public deployment is claimed.
- n8n and Google node setup is external and is not included in the repository.
- Approved Gmail actions create draft-only or mock data; no email is sent.

## Security Notes

- Never commit `backend/.env`, `n8n-webhook-info*`, approval ledger data,
  approved note artifacts, `node_modules`, `dist`, `__pycache__`, `.venv`, or
  submission evidence containing secrets.
- Keep real webhook tokens and API keys only in local environment files.