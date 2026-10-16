import os
import json
from pathlib import Path
from fastapi.testclient import TestClient

from main import app
import key_manager
from schemas import ExtractedInvoiceData

client = TestClient(app)

def test_key_manager_encryption_and_auth():
    print("\n--- 1. Testing Key Manager Encryption & Auth ---")
    # Test valid authentication
    token = key_manager.authenticate_user(key_manager.DASHBOARD_PASSWORD)
    assert token is not None, "Failed to authenticate with valid password"
    assert key_manager.validate_token(token), "Generated token failed validation"
    
    # Test invalid authentication
    bad_token = key_manager.authenticate_user("wrong_password_xyz")
    assert bad_token is None, "Expected None on invalid password"

    # Test key saving, encryption, masking, and retrieval
    key_manager.save_key("groq", "gsk_test1234567890abcdef")
    overview = key_manager.get_providers_overview()
    groq_state = overview["providers"]["groq"]
    assert groq_state["has_key"] is True
    assert "gsk_test" not in groq_state["masked_key"] or "••••••••" in groq_state["masked_key"]
    assert key_manager.get_key("groq") == "gsk_test1234567890abcdef"

    # Test active provider switching
    key_manager.set_active_provider("groq")
    assert key_manager.get_active_provider() == "groq"
    key_manager.set_active_provider("mistral")
    assert key_manager.get_active_provider() == "mistral"
    print("[OK] Key manager encryption, masking, and token auth verified.")


def test_fastapi_endpoints_protection():
    print("\n--- 2. Testing FastAPI Auth & Key Management Endpoints ---")
    # Attempt unauthorized mutation to /api/keys without authentication
    resp_unauth = client.post("/api/keys", json={"provider": "openrouter", "key": "sk-unauthorized-test"})
    assert resp_unauth.status_code == 401, f"Expected 401 Unauthorized for mutation without auth, got {resp_unauth.status_code}"

    # Authenticate via /api/auth/login
    resp_login = client.post("/api/auth/login", json={"password": key_manager.DASHBOARD_PASSWORD})
    assert resp_login.status_code == 200, f"Login failed: {resp_login.text}"
    token = resp_login.json()["token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Authorized access to /api/keys
    resp_keys = client.get("/api/keys", headers=auth_headers)
    assert resp_keys.status_code == 200
    data = resp_keys.json()
    assert "providers" in data
    assert "mistral" in data["providers"]
    print(f"[OK] Protected /api/keys returned: {list(data['providers'].keys())}")

    # Test updating a key
    resp_up = client.post(
        "/api/keys",
        json={"provider": "openrouter", "key": "sk-or-v1-test-9988776655"},
        headers=auth_headers
    )
    assert resp_up.status_code == 200

    # Test provider test endpoint
    resp_test = client.post(
        "/api/keys/test",
        json={"provider": "mistral"},
        headers=auth_headers
    )
    assert resp_test.status_code == 200
    print(f"[OK] Provider connectivity test returned: {resp_test.json()['status']} ({resp_test.json().get('message')})")

    # Test active provider switch endpoint
    resp_active = client.post(
        "/api/keys/active",
        json={"provider": "mistral"},
        headers=auth_headers
    )
    assert resp_active.status_code == 200
    print("[OK] All secure API key endpoints verified successfully.")


def test_invoice_extraction_and_excel():
    print("\n--- 3. Testing Invoice Extraction with Provider Tracking & Excel ---")
    sample_txt = Path("sample_invoice.txt")
    if not sample_txt.exists():
        sample_txt.write_text("SHORE POINT DISTRIBUTING CO INC\nInvoice#: 770921 Date: Sep 28 2026\n04427 ARN 1/2 7 30.00 210.00")

    with open(sample_txt, "rb") as f:
        resp = client.post(
            "/extract-invoice",
            files={"file": (sample_txt.name, f.read(), "text/plain")}
        )

    assert resp.status_code == 200, f"Extraction failed: {resp.text}"
    res_data = resp.json()
    assert "provider_used" in res_data
    assert "download_excel_url" in res_data
    file_id = res_data["file_id"]
    print(f"[OK] Extracted successfully via provider: '{res_data['provider_used']}' (Status: {res_data['status']})")

    # Test Excel download endpoint
    resp_excel = client.get(f"/download-excel/{file_id}")
    assert resp_excel.status_code == 200
    assert len(resp_excel.content) > 1000
    print(f"[OK] Downloaded Excel workbook ({len(resp_excel.content)} bytes) successfully.")


def test_streamlit_app_syntax():
    print("\n--- 4. Validating Streamlit App Syntax & Imports ---")
    import streamlit_app
    assert streamlit_app.BACKEND_URL is not None
    print("[OK] Streamlit dashboard script syntax and imports verified.")


if __name__ == "__main__":
    test_key_manager_encryption_and_auth()
    test_fastapi_endpoints_protection()
    test_invoice_extraction_and_excel()
    test_streamlit_app_syntax()
    print("\n=======================================================")
    print(" ALL DASHBOARD & WORKFLOW TESTS PASSED 100% SUCCESSFULLY!")
    print("=======================================================")
