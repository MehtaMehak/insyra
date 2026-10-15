import csv
import io
import json
import os
import re
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from services.weekly_pulse import WeeklyPulseError, WeeklyPulseResult, generate_weekly_pulse
from services.fee_explainer import generate_fee_explainer_json
from services.approval_ledger import ApprovalLedger, ApprovalLedgerError

app = FastAPI(title="Insyra API")


def get_cors_allowed_origins(environ=None) -> list[str]:
    source = os.environ if environ is None else environ
    raw = source.get("CORS_ALLOWED_ORIGINS")
    if raw is None:
        candidates = ["http://localhost:5173", "http://127.0.0.1:5173"]
    else:
        candidates = [item.strip() for item in str(raw).split(",")]

    allowed: list[str] = []
    seen: set[str] = set()
    for origin in candidates:
        if not origin or origin == "*":
            continue
        if origin not in seen:
            seen.add(origin)
            allowed.append(origin)
    return allowed


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        allowed_origins = get_cors_allowed_origins()
        origin_allowed = bool(origin and origin in allowed_origins)

        if request.method == "OPTIONS":
            response = Response(status_code=200)
            if origin_allowed and origin is not None:
                response.headers["access-control-allow-origin"] = origin
                response.headers["access-control-allow-credentials"] = "true"
                response.headers["access-control-allow-methods"] = (
                    "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
                )
                requested_headers = request.headers.get(
                    "access-control-request-headers"
                )
                response.headers["access-control-allow-headers"] = (
                    requested_headers if requested_headers else "*"
                )
                response.headers["vary"] = "Origin"
            return response

        response = await call_next(request)
        if origin_allowed and origin is not None:
            response.headers["access-control-allow-origin"] = origin
            response.headers["access-control-allow-credentials"] = "true"
            response.headers["vary"] = "Origin"
        return response


app.add_middleware(DynamicCORSMiddleware)

MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024
DEMO_READ_ONLY_MESSAGE = (
    "This Insyra instance is in read-only demo mode; state-changing "
    "operations are disabled."
)


def is_demo_read_only(environ=None) -> bool:
    source = os.environ if environ is None else environ
    value = str(source.get("DEMO_READ_ONLY", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


# Compatibility aliases for tests or alternate callers.
demo_read_only_enabled = is_demo_read_only
demo_mode_enabled = is_demo_read_only


def _require_mutable_operation() -> None:
    if is_demo_read_only():
        raise HTTPException(status_code=403, detail=DEMO_READ_ONLY_MESSAGE)
INSIGHTS_FILE = Path(__file__).resolve().parent / "data" / "ai_analysis.json"
APPROVALS_FILE = Path(__file__).resolve().parent / "data" / "approvals.json"
REQUIRED_COLUMNS = {"date", "review", "rating"}


@app.get("/")
def root() -> dict:
    return {"message": "Insyra API is running"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/insights")
def get_insights() -> dict:
    if not INSIGHTS_FILE.is_file():
        raise HTTPException(
            status_code=404,
            detail="AI analysis has not been generated yet.",
        )

    try:
        with INSIGHTS_FILE.open("r", encoding="utf-8") as insights_file:
            data = json.load(insights_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Saved AI analysis is missing or invalid.",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="Saved AI analysis has an invalid structure.",
        )

    return data


def _serve_committed_weekly_pulse() -> dict:
    pulse_path = Path(__file__).resolve().parent / "data" / "weekly_pulse.md"
    if not pulse_path.is_file():
        raise HTTPException(
            status_code=500,
            detail="Weekly Product Pulse report is not available in read-only demo mode.",
        )

    try:
        report = pulse_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Weekly Product Pulse report could not be read.",
        ) from exc

    date_match = re.search(r"^Report date:\s*(.+)$", report, re.MULTILINE)
    report_date = date_match.group(1).strip() if date_match else ""

    themes: list[str] = []
    in_themes = False
    for line in report.splitlines():
        if line.startswith("## "):
            in_themes = line.startswith("## Top")
            continue
        if in_themes:
            match = re.match(r"^\d+\.\s+(.+)$", line.strip())
            if match:
                themes.append(match.group(1).strip())

    verified_quotes: list[dict[str, str]] = []
    in_quotes = False
    for line in report.splitlines():
        if line.startswith("## "):
            in_quotes = "Verified customer quotes" in line
            continue
        if in_quotes:
            match = re.match(
                r'^>\s*"(.*)"\s*-\s*source:\s*(.+)$',
                line.strip(),
            )
            if match:
                verified_quotes.append(
                    {
                        "quote": match.group(1).strip(),
                        "source": match.group(2).strip(),
                        "rating": "",
                        "date": "",
                    }
                )

    fee_observation = ""
    in_fee = False
    for line in report.splitlines():
        if line.startswith("## "):
            in_fee = "Fee-confusion observation" in line
            continue
        if in_fee and line.strip():
            fee_observation = (
                fee_observation + "\n" + line.strip()
                if fee_observation
                else line.strip()
            )

    recommended_actions: list[str] = []
    in_actions = False
    for line in report.splitlines():
        if line.startswith("## "):
            in_actions = "Recommended actions" in line
            continue
        if in_actions:
            match = re.match(r"^\d+\.\s+(.+)$", line.strip())
            if match:
                recommended_actions.append(match.group(1).strip())

    result = WeeklyPulseResult(
        report_date=report_date,
        report=report + "\n",
        word_count=len(report.split()),
        supported_themes=themes,
        verified_quotes=verified_quotes,
        fee_observation=fee_observation.strip(),
        recommended_actions=recommended_actions,
        sample_size=300,
        total_review_count=12680,
    )
    return result.as_dict()


@app.get("/api/weekly-pulse")
def weekly_pulse(report_date: str | None = None) -> dict:
    if is_demo_read_only():
        return _serve_committed_weekly_pulse()

    try:
        result = generate_weekly_pulse(report_date=report_date)
    except (WeeklyPulseError, ValueError) as exc:
        detail = str(exc)
        status_code = 404 if "does not exist" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from None

    return result.as_dict()


@app.get("/api/fee-explainer")
def fee_explainer() -> dict:
    if is_demo_read_only():
        fee_path = Path(__file__).resolve().parent / "data" / "fee_explainer.json"
        if not fee_path.is_file():
            raise HTTPException(
                status_code=500,
                detail="Fee explainer report is not available in read-only demo mode.",
            )
        try:
            with fee_path.open("r", encoding="utf-8") as fee_file:
                data = json.load(fee_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500,
                detail="Fee explainer report could not be read.",
            ) from exc
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=500,
                detail="Fee explainer report has an invalid structure.",
            )
        return data

    try:
        return generate_fee_explainer_json()
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        detail = str(exc)
        status_code = 404 if "does not exist" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/api/approvals")
def list_approvals() -> dict:
    ledger = ApprovalLedger(APPROVALS_FILE)
    try:
        approvals = ledger.list_requests()
    except ApprovalLedgerError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    return {
        "approvals": approvals,
        "items": approvals,
        "requests": approvals,
    }


@app.post("/api/approvals")
def create_approval(payload: dict | None = Body(default=None)) -> dict:
    _require_mutable_operation()
    ledger = ApprovalLedger(APPROVALS_FILE)
    try:
        approval = ledger.create_request(payload)
    except (ApprovalLedgerError, ValueError) as exc:
        detail = str(exc)
        status_code = 404 if "does not exist" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from None
    return approval


@app.post("/api/approvals/{request_id}/approve")
def approve_approval(request_id: str, payload: dict | None = Body(default=None)) -> dict:
    _require_mutable_operation()
    ledger = ApprovalLedger(APPROVALS_FILE)
    try:
        from services.mcp_client_adapter import (
            create_default_approval_providers,
            get_approval_provider_mode,
        )

        notes_provider, gmail_provider = create_default_approval_providers()
        return ledger.approve_request(
            request_id,
            payload,
            execute_providers=True,
            notes_provider=notes_provider,
            gmail_provider=gmail_provider,
            provider_mode=get_approval_provider_mode(),
        )
    except ApprovalLedgerError as exc:
        detail = str(exc)
        if "does not exist" in detail:
            raise HTTPException(status_code=404, detail=detail) from None
        if "missing required fields" in detail or "snapshot" in detail.lower():
            raise HTTPException(status_code=400, detail=detail) from None
        raise HTTPException(status_code=409, detail=detail) from None


@app.post("/api/approvals/{request_id}/reject")
def reject_approval(request_id: str, payload: dict | None = Body(default=None)) -> dict:
    _require_mutable_operation()
    ledger = ApprovalLedger(APPROVALS_FILE)
    try:
        return ledger.reject_request(request_id, payload)
    except ApprovalLedgerError as exc:
        detail = str(exc)
        if "does not exist" in detail:
            raise HTTPException(status_code=404, detail=detail) from None
        raise HTTPException(status_code=409, detail=detail) from None


@app.post("/api/reviews/upload")
async def upload_reviews(file: UploadFile = File(...)) -> dict:
    _require_mutable_operation()
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must have a .csv extension.",
        )

    content = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must be 5 MB or smaller.",
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="CSV file must be valid UTF-8.",
        ) from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fieldnames = reader.fieldnames or []
        missing_columns = REQUIRED_COLUMNS - set(fieldnames)
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=(
                    "CSV is missing required columns: "
                    + ", ".join(sorted(missing_columns))
                ),
            )

        valid_rows = []
        for row in reader:
            if not row:
                continue

            values = [value for value in row.values() if value is not None]
            if not any(str(value).strip() for value in values):
                continue

            review_value = row.get("review")
            if review_value is None or not str(review_value).strip():
                continue

            valid_rows.append(
                {
                    column: row.get(column)
                    for column in fieldnames
                    if column is not None
                }
            )

        if not valid_rows:
            raise HTTPException(
                status_code=400,
                detail="CSV file contains no review rows.",
            )

        return {
            "filename": file.filename,
            "total_reviews": len(valid_rows),
            "preview": valid_rows[:5],
            "message": "CSV file validated successfully.",
        }
    except csv.Error as exc:
        raise HTTPException(
            status_code=400,
            detail="CSV file is malformed.",
        ) from exc
