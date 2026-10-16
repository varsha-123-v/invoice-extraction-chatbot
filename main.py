import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import UPLOADS_DIR, EXPORTS_DIR, MISTRAL_API_KEY, MISTRAL_VISION_MODEL
from schemas import ExtractedInvoiceData, ExtractionResponse
from extractor import process_invoice_extraction
from validator import validate_invoice_data
from excel_generator import generate_invoice_excel
import key_manager

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main")

app = FastAPI(
    title="Invoice Extraction & Automation API",
    description="FastAPI Backend for 2-Pass Invoice OCR & Handwritten extraction using Mistral AI, mathematical validation, and multi-sheet Excel generation.",
    version="1.0.0",
)

# CORS Middleware for Frontend / Web Client Access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_dashboard_auth(request: Request):
    """Enforces authentication for secure dashboard & key management operations."""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif request.headers.get("X-Dashboard-Token"):
        token = request.headers.get("X-Dashboard-Token")
    elif request.headers.get("X-Dashboard-Password"):
        if request.headers.get("X-Dashboard-Password") == key_manager.DASHBOARD_PASSWORD:
            return True

    if token and key_manager.validate_token(token):
        return True

    raise HTTPException(status_code=401, detail="Unauthorized: Invalid or missing dashboard authentication credentials.")


@app.get("/")
def read_root():
    return {
        "name": "Invoice Extraction & Automation API",
        "status": "online",
        "active_provider": key_manager.get_active_provider(),
        "providers": key_manager.get_providers_overview()["providers"],
        "endpoints": {
            "extract_invoice": "POST /extract-invoice",
            "download_excel": "GET /download-excel/{file_id}",
            "health": "GET /health",
            "api_keys": "GET /api/keys",
            "api_keys_test": "POST /api/keys/test"
        }
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "active_provider": key_manager.get_active_provider(),
        "fallback_order": key_manager.get_fallback_order(),
        "uploads_directory": str(UPLOADS_DIR),
        "exports_directory": str(EXPORTS_DIR),
        "keys_configured": {p: bool(key_manager.get_key(p)) for p in ["mistral", "groq", "openrouter"]}
    }


@app.post("/api/auth/login")
def login(payload: Dict[str, str]):
    """Authenticates the dashboard user and issues a secure session token."""
    password = payload.get("password", "")
    token = key_manager.authenticate_user(password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid dashboard password.")
    return {"token": token, "status": "authenticated", "message": "Login successful."}


@app.get("/api/keys")
def list_keys(request: Request):
    """
    Returns safe, masked provider info, health status, and active preference.
    Masked keys (e.g. mstrl_••••••••3ZDn) are safe for frontend rendering and never expose secret values.
    """
    overview = key_manager.get_providers_overview()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else request.headers.get("X-Dashboard-Token")
    is_auth = (token and key_manager.validate_token(token)) or (request.headers.get("X-Dashboard-Password") == key_manager.DASHBOARD_PASSWORD)
    overview["authenticated"] = bool(is_auth)
    return overview


@app.post("/api/keys")
def update_key(payload: Dict[str, str], auth: bool = Depends(require_dashboard_auth)):
    """Securely encrypts and saves an API key on the backend."""
    provider = payload.get("provider", "")
    key = payload.get("key", "")
    if not provider or not key:
        raise HTTPException(status_code=400, detail="Provider and key must be provided.")
    key_manager.save_key(provider, key)
    return {"status": "success", "message": f"API key for {provider} saved securely."}


@app.delete("/api/keys/{provider}")
def remove_key(provider: str, auth: bool = Depends(require_dashboard_auth)):
    """Deletes the stored key for a provider."""
    key_manager.delete_key(provider)
    return {"status": "success", "message": f"API key for {provider} removed."}


@app.post("/api/keys/test")
def test_key(payload: Dict[str, str], auth: bool = Depends(require_dashboard_auth)):
    """Tests live API connectivity and authentication for a provider."""
    provider = payload.get("provider", "")
    key = payload.get("key")
    return key_manager.test_provider_key(provider, key)


@app.post("/api/keys/active")
def switch_active_provider(payload: Dict[str, str], auth: bool = Depends(require_dashboard_auth)):
    """Switches the preferred active provider without modifying code."""
    provider = payload.get("provider", "")
    if not provider:
        raise HTTPException(status_code=400, detail="Provider must be specified.")
    success = key_manager.set_active_provider(provider)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set active provider: {provider}")
    return {"status": "success", "active_provider": provider}


@app.post("/extract-invoice", response_model=ExtractionResponse)
async def extract_invoice(request: Request, file: UploadFile = File(...)):
    """
    Accepts an uploaded invoice PDF or image file (PNG, JPG, TIFF),
    extracts complete printed document details in Pass 1 and handwritten notes separately in Pass 2
    using Mistral AI Vision models, validates line item math & totals,
    generates a 3-sheet Excel (.xlsx) report, and returns structured JSON with a download link.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded or filename is empty.")

    # Generate unique ID for this processing session
    file_id = str(uuid.uuid4())[:8]
    ext = Path(file.filename).suffix or ".pdf"
    saved_filename = f"{file_id}_{file.filename}"
    upload_path = UPLOADS_DIR / saved_filename

    logger.info(f"Receiving file '{file.filename}' -> saving to '{upload_path}'")

    try:
        # Save file to temporary uploads directory
        contents = await file.read()
        with open(upload_path, "wb") as f:
            f.write(contents)

        # 1. Execute 2-Pass Extraction Pipeline
        extraction_res = process_invoice_extraction(upload_path)
        raw_header, raw_line_items = extraction_res.header, extraction_res.line_items

        # Ensure extraction produced valid data; do not generate empty reports or return 200 OK
        if not raw_line_items:
            raise HTTPException(
                status_code=422,
                detail=f"Extraction failed for '{file.filename}': No line items could be extracted from the invoice."
            )

        # 2. Execute Validation & Mathematical Auditing
        validated_header, validated_items, validation_result = validate_invoice_data(raw_header, raw_line_items)

        extracted_data = ExtractedInvoiceData(
            header=validated_header,
            line_items=validated_items,
            validation=validation_result,
            detected_table_headers=extraction_res.detected_table_headers,
        )

        # 3. Generate 3-Sheet Excel Workbook
        excel_filename = f"Extracted_Invoice_{file_id}.xlsx"
        excel_output_path = EXPORTS_DIR / excel_filename
        generate_invoice_excel(extracted_data, excel_output_path)

        # Construct download link URL
        base_url = str(request.base_url).rstrip("/")
        download_url = f"{base_url}/download-excel/{file_id}"

        return ExtractionResponse(
            file_id=file_id,
            filename=file.filename,
            download_excel_url=download_url,
            extracted_data=extracted_data,
            provider_used=getattr(extraction_res, "provider_used", "Mistral AI"),
            status="success" if validation_result.is_valid else "discrepancy_detected"
        )

    except HTTPException:
        raise
    except RuntimeError as re_err:
        logger.error(f"Invoice extraction error: {re_err}")
        raise HTTPException(status_code=422, detail=str(re_err))
    except Exception as e:
        logger.error(f"Error processing invoice extraction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Invoice processing failed: {str(e)}")


@app.get("/download-excel/{file_id}")
def download_excel(file_id: str):
    """
    Downloads the generated 3-sheet Excel report workbook for a processed invoice session ID.
    """
    excel_filename = f"Extracted_Invoice_{file_id}.xlsx"
    excel_path = EXPORTS_DIR / excel_filename

    if not excel_path.exists():
        raise HTTPException(status_code=404, detail=f"Excel file for ID '{file_id}' not found.")

    return FileResponse(
        path=excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=excel_filename
    )
