import csv
import io
import json
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile

from services.weekly_pulse import WeeklyPulseError, generate_weekly_pulse
from services.fee_explainer import generate_fee_explainer_json
from services.approval_ledger import ApprovalLedger, ApprovalLedgerError
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Insyra API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024
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


@app.get("/api/weekly-pulse")
def weekly_pulse(report_date: str | None = None) -> dict:
    try:
        result = generate_weekly_pulse(report_date=report_date)
    except (WeeklyPulseError, ValueError) as exc:
        detail = str(exc)
        status_code = 404 if "does not exist" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from None

    return result.as_dict()


@app.get("/api/fee-explainer")
def fee_explainer() -> dict:
    try:
        return generate_fee_explainer_json()
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        detail = str(exc)
        status_code = 404 if "does not exist" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return result.as_dict()


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
