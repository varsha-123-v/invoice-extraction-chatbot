import os
import json
import io
import requests
import streamlit as st
import pandas as pd
from typing import Dict, Any, List, Optional

# -------------------------------------------------------------
# Configuration & Backend Connection Setup
# -------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(
    page_title="Purchase Invoice Automation",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern styling
st.markdown("""
<style>
    /* Metric Card Styling */
    div[data-testid="stMetric"] {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px 16px;
    }
    div[data-testid="stMetricLabel"] {
        color: #94a3b8;
        font-weight: 500;
    }
    div[data-testid="stMetricValue"] {
        color: #f8fafc;
        font-weight: 700;
    }
    /* Provider Badge */
    .provider-chip {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.82rem;
        font-weight: 600;
        background: #0f172a;
        border: 1px solid #3b82f6;
        color: #60a5fa;
        margin-bottom: 8px;
    }
    .status-active { color: #22c55e; font-weight: bold; }
    .status-error { color: #ef4444; font-weight: bold; }
    .status-warning { color: #f59e0b; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# -------------------------------------------------------------
# Helper Functions for Backend API Communication
# -------------------------------------------------------------
def get_auth_headers() -> Dict[str, str]:
    token = st.session_state.get("auth_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def check_backend_health() -> Dict[str, Any]:
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if resp.status_code == 200:
            return {"online": True, **resp.json()}
        return {"online": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"online": False, "error": str(e)}


def login_user(password: str) -> bool:
    try:
        resp = requests.post(f"{BACKEND_URL}/api/auth/login", json={"password": password}, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            st.session_state["auth_token"] = data.get("token")
            st.session_state["authenticated"] = True
            return True
        else:
            return False
    except Exception:
        return False


def fetch_keys_overview() -> Dict[str, Any]:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/keys", headers=get_auth_headers(), timeout=6)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            st.session_state["authenticated"] = False
            return {}
    except Exception as e:
        st.error(f"Failed to fetch keys from backend: {e}")
    return {}


def save_provider_key(provider: str, key_val: str) -> bool:
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/keys",
            json={"provider": provider, "key": key_val},
            headers=get_auth_headers(),
            timeout=8
        )
        return resp.status_code == 200
    except Exception:
        return False


def delete_provider_key(provider: str) -> bool:
    try:
        resp = requests.delete(f"{BACKEND_URL}/api/keys/{provider}", headers=get_auth_headers(), timeout=8)
        return resp.status_code == 200
    except Exception:
        return False


def test_provider_connection(provider: str, key_val: Optional[str] = None) -> Dict[str, Any]:
    try:
        payload = {"provider": provider}
        if key_val:
            payload["key"] = key_val
        resp = requests.post(f"{BACKEND_URL}/api/keys/test", json=payload, headers=get_auth_headers(), timeout=18)
        return resp.json() if resp.status_code == 200 else {"success": False, "message": resp.text}
    except Exception as e:
        return {"success": False, "message": str(e)}


def set_active_preference(provider: str) -> bool:
    try:
        resp = requests.post(f"{BACKEND_URL}/api/keys/active", json={"provider": provider}, headers=get_auth_headers(), timeout=8)
        return resp.status_code == 200
    except Exception:
        return False


# -------------------------------------------------------------
# Auto-Authentication Setup (No blocking login prompt)
# -------------------------------------------------------------
if "authenticated" not in st.session_state or not st.session_state.get("authenticated"):
    st.session_state["authenticated"] = True
    try:
        login_user(os.environ.get("DASHBOARD_PASSWORD", "admin123"))
    except Exception:
        pass


# -------------------------------------------------------------
# MAIN DASHBOARD INTERFACE (Authenticated)
# -------------------------------------------------------------
health_info = check_backend_health()

# =============================================================
# LEFT SIDEBAR: API Key Management
# =============================================================
with st.sidebar:
    st.markdown("### ⚙️ API Key Management")
    st.caption("Secure server-side secrets with automatic multi-provider failover.")
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state["auth_token"] = None
        st.rerun()

    st.divider()

    # Load provider states from backend
    keys_data = fetch_keys_overview()
    providers_info = keys_data.get("providers", {})
    active_pref = keys_data.get("active_provider", "mistral")

    st.markdown("#### 1. Provider Selection")
    provider_options = {
        "mistral": "Mistral AI (Primary Vision)",
        "openrouter": "OpenRouter (Gemini / Multi-LLM)",
        "groq": "Groq (Fast Llama-Vision)"
    }
    selected_p = st.selectbox(
        "Select Provider to Configure",
        options=list(provider_options.keys()),
        format_func=lambda x: provider_options[x],
        index=list(provider_options.keys()).index(active_pref) if active_pref in provider_options else 0
    )

    curr_p_state = providers_info.get(selected_p, {})
    curr_status = curr_p_state.get("status", "Not Configured")
    curr_masked = curr_p_state.get("masked_key", "")
    curr_err = curr_p_state.get("error_message")

    # Status Chip
    if curr_status == "Active":
        st.markdown(f"Status: :green[**● Active**]")
    elif curr_status == "Rate Limit Exceeded":
        st.markdown(f"Status: :orange[**▲ Rate Limit Exceeded**]")
    elif curr_status == "Quota Exhausted":
        st.markdown(f"Status: :red[**✖ Quota Exhausted**]")
    elif curr_status == "Invalid Key":
        st.markdown(f"Status: :red[**✖ Invalid Key**]")
    elif curr_status == "Error":
        st.markdown(f"Status: :red[**✖ Error**]")
    else:
        st.markdown(f"Status: :gray[**○ Not Configured**]")

    if curr_masked:
        st.markdown(f"**Current Stored Key:** `{curr_masked}`")
    else:
        st.caption("No key currently stored on backend.")

    if curr_err:
        st.warning(f"Provider Error: {curr_err}")

    # Set as preferred active button
    if selected_p != active_pref:
        if st.button(f"Make {selected_p.capitalize()} Preferred", use_container_width=True):
            if set_active_preference(selected_p):
                st.success(f"Preferred active provider set to {selected_p.capitalize()}!")
                st.rerun()

    st.markdown("---")
    st.markdown("#### 2. Update / Add Key")
    show_key = st.checkbox("Show plain text key while typing", key="show_key_toggle")
    new_key = st.text_input(
        f"Enter new {selected_p.capitalize()} Key",
        type="default" if show_key else "password",
        placeholder="Paste API Key here...",
        key=f"input_key_{selected_p}"
    )

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("💾 Save Key", use_container_width=True):
            if new_key.strip():
                if save_provider_key(selected_p, new_key.strip()):
                    st.success(f"{selected_p.capitalize()} key saved securely!")
                    st.rerun()
                else:
                    st.error("Failed to save key.")
            else:
                st.warning("Please enter a key.")

    with btn_col2:
        if st.button("🧪 Test Key", use_container_width=True):
            with st.spinner(f"Testing {selected_p.capitalize()} API..."):
                res = test_provider_connection(selected_p, new_key.strip() if new_key else None)
                if res.get("success"):
                    st.success(res.get("message"))
                else:
                    st.error(res.get("message"))

    if curr_p_state.get("has_key"):
        if st.button("🗑️ Remove Stored Key", use_container_width=True):
            if delete_provider_key(selected_p):
                st.info(f"{selected_p.capitalize()} key deleted.")
                st.rerun()

    st.divider()
    st.markdown("#### 🔄 Automatic Failover Order")
    st.caption("If a provider hits a rate limit or quota exhaustion, extraction automatically falls over to the next configured provider:")
    
    order = [active_pref] + [p for p in ["mistral", "openrouter", "groq"] if p != active_pref]
    for idx, p in enumerate(order, 1):
        p_stat = providers_info.get(p, {}).get("status", "Not Configured")
        icon = "🟢" if p_stat == "Active" else ("🟠" if "Rate" in p_stat else ("🔴" if "Quota" in p_stat or "Invalid" in p_stat else "⚪"))
        prefix = "★ [Preferred] " if p == active_pref else f"{idx}. "
        st.markdown(f"**{prefix}{p.capitalize()}**: {icon} {p_stat}")


# =============================================================
# RIGHT MAIN PANEL: Multi-Invoice Extraction & Chatbot
# =============================================================
header_col1, header_col2 = st.columns([3, 1])
with header_col1:
    st.title("🧾 Intelligent Invoice Extraction & Audit")
    st.caption("Automated document processing with dynamic column detection, mathematical cross-check, handwritten notes extraction, and multi-sheet Excel generation.")
with header_col2:
    if health_info.get("online"):
        st.success(f"🟢 Backend Online\nActive: {health_info.get('active_provider', 'Mistral').capitalize()}")
    else:
        st.error(f"🔴 Backend Offline\n{health_info.get('error', 'Cannot reach FastAPI')}")

# Store extracted results across sessions
if "extractions" not in st.session_state:
    st.session_state["extractions"] = []

# Section 1: Upload Documents
st.markdown("### 📤 Upload Purchase Invoices")
st.caption("Upload any PDF or image invoice. Text, line items, and totals are extracted immediately without questions.")

uploaded_files = st.file_uploader(
    "Choose PDF or image files to extract",
    type=["pdf", "png", "jpg", "jpeg", "tiff", "txt"],
    accept_multiple_files=True,
    help="Supports multi-page supplier invoices, scanned receipts, and manifests from any distributor."
)

if uploaded_files:
    # Check for new files not yet processed in this session
    already_extracted_names = {item["filename"] for item in st.session_state["extractions"]}
    pending_files = [f for f in uploaded_files if f.name not in already_extracted_names]

    # Quick manual trigger button if needed
    col_act1, col_act2 = st.columns([2, 5])
    with col_act1:
        force_reextract = st.button("⚡ Re-Extract All Uploads", use_container_width=True)

    files_to_process = uploaded_files if force_reextract else pending_files

    if force_reextract:
        st.session_state["extractions"] = []

    if files_to_process:
        st.info(f"⚡ **Extracting text and line items from {len(files_to_process)} document(s)...**")
        progress_bar = st.progress(0)
        status_box = st.empty()

        for idx, up_file in enumerate(files_to_process):
            file_num = idx + 1
            progress_pct = int((idx / len(files_to_process)) * 100)
            progress_bar.progress(progress_pct)
            status_box.markdown(f"⏳ **Extracting text from `{up_file.name}` ({file_num}/{len(files_to_process)})...**")

            try:
                files = {"file": (up_file.name, up_file.getvalue(), up_file.type or "application/pdf")}
                resp = requests.post(f"{BACKEND_URL}/extract-invoice", files=files, timeout=180)

                if resp.status_code == 200:
                    ext_json = resp.json()
                    st.session_state["extractions"].append({
                        "filename": up_file.name,
                        "success": True,
                        "data": ext_json
                    })
                else:
                    err_detail = "Extraction error"
                    try:
                        err_detail = resp.json().get("detail", resp.text)
                    except Exception:
                        err_detail = resp.text

                    st.session_state["extractions"].append({
                        "filename": up_file.name,
                        "success": False,
                        "error": err_detail
                    })

            except Exception as ex:
                st.session_state["extractions"].append({
                    "filename": up_file.name,
                    "success": False,
                    "error": str(ex)
                })

        progress_bar.progress(100)
        status_box.success("🎉 Document extraction complete!")
        st.rerun()


# =============================================================
# Section 2: Extraction Results Display
# =============================================================
if st.session_state["extractions"]:
    st.markdown("---")
    res_hdr_col1, res_hdr_col2 = st.columns([4, 1])
    with res_hdr_col1:
        st.markdown(f"### 📊 Extracted Invoices ({len(st.session_state['extractions'])} documents)")
    with res_hdr_col2:
        if st.button("🧹 Clear Results", use_container_width=True):
            st.session_state["extractions"] = []
            st.rerun()

    for item_idx, item in enumerate(st.session_state["extractions"]):
        fname = item["filename"]
        is_succ = item["success"]

        if not is_succ:
            with st.expander(f"❌ {fname} — Extraction Failed", expanded=True):
                st.error(f"Failed to extract '{fname}': {item.get('error', 'Unknown error')}")
                st.caption("Tip: Ensure the document contains readable text/images or verify API keys.")
            continue

        resp_data = item["data"]
        extracted = resp_data.get("extracted_data", {})
        header = extracted.get("header", {})
        line_items = extracted.get("line_items", [])
        validation = extracted.get("validation", {})
        file_id = resp_data.get("file_id", "")
        provider_used = resp_data.get("provider_used", "Mistral AI")

        is_valid = validation.get("is_valid", False)
        vendor_disp = header.get("vendor_name") or "Extracted Invoice"
        inv_total = header.get("invoice_total") or 0.0
        title_icon = "✅" if is_valid else "⚠️"
        expander_title = f"{title_icon} {vendor_disp} — {fname} | Total: ${inv_total:,.2f}"

        with st.expander(expander_title, expanded=True):
            # Action & Status Header
            col_b1, col_b2, col_b3 = st.columns([2, 2, 2])
            with col_b1:
                st.markdown(f"<div class='provider-chip'>⚡ Extracted via: <b>{provider_used}</b></div>", unsafe_allow_html=True)
            with col_b2:
                if is_valid:
                    st.success("✓ Math Cross-Check Verified")
                else:
                    st.warning("⚠️ Discrepancy or Missing Subtotals")
            with col_b3:
                # Direct Excel download button
                try:
                    excel_resp = requests.get(f"{BACKEND_URL}/download-excel/{file_id}", timeout=10)
                    if excel_resp.status_code == 200:
                        st.download_button(
                            label="📥 Download Excel (.xlsx)",
                            data=excel_resp.content,
                            file_name=f"Extracted_{fname.replace('.pdf', '')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_btn_{file_id}_{item_idx}",
                            use_container_width=True
                        )
                except Exception:
                    st.caption(f"Excel link: [Download]({resp_data.get('download_excel_url', '')})")

            # Key Metrics
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.metric("Vendor", header.get("vendor_name") or "N/A")
            with m2:
                st.metric("Invoice #", header.get("invoice_number") or "N/A")
            with m3:
                st.metric("PO #", header.get("po_number") or header.get("handwritten_po_number") or "N/A")
            with m4:
                st.metric("Total ($)", f"${inv_total:,.2f}")
            with m5:
                st.metric("Line Items", len(line_items))

            # Audit Discrepancies if any
            if not is_valid:
                diff = validation.get("total_difference", 0.0)
                extracted_tot = validation.get("extracted_invoice_total", 0.0)
                calc_tot = validation.get("calculated_line_items_total", 0.0)
                disc_notes = validation.get("summary_notes", [])
                st.warning(
                    f"**Audit Note**: Extracted total (${extracted_tot or 0.0:,.2f}) vs line sum (${calc_tot:,.2f}). Difference: **${diff:,.2f}**.\n\n"
                    + "\n".join(f"- {n}" for n in disc_notes)
                )

            # Handwritten Notes
            hw_notes = header.get("handwritten_notes")
            if hw_notes:
                st.info(f"✍️ **Handwritten Annotations Extracted:**\n{hw_notes}")

            # Extracted Tabs: Line items table & Extracted text fields
            tab_table, tab_text, tab_json = st.tabs(["📋 Extracted Line Items", "📝 Extracted Text & Details", "🔍 Raw JSON"])

            with tab_table:
                if line_items:
                    rows = []
                    for li in line_items:
                        rows.append({
                            "Line #": li.get("line_number"),
                            "Item Code": li.get("item_number") or "-",
                            "Description": li.get("description"),
                            "Qty": li.get("quantity"),
                            "Unit Price ($)": li.get("unit_price"),
                            "Line Total ($)": li.get("line_total"),
                            "Status / Flag": li.get("special_flag") or "OK",
                            "Handwritten Note": li.get("handwritten_note") or "-",
                            "Raw Columns": json.dumps(li.get("raw_columns", {})) if li.get("raw_columns") else "-"
                        })
                    df = pd.DataFrame(rows)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.caption("No line items detected in document.")

            with tab_text:
                st.markdown("#### Document Header & Extracted Text Fields")
                header_display = [
                    {"Field": "Vendor Name", "Extracted Value": header.get("vendor_name") or "-"},
                    {"Field": "Vendor Address", "Extracted Value": header.get("vendor_address") or "-"},
                    {"Field": "Vendor Phone", "Extracted Value": header.get("vendor_phone") or "-"},
                    {"Field": "Account Number", "Extracted Value": header.get("account_number") or "-"},
                    {"Field": "License Number", "Extracted Value": header.get("license_number") or "-"},
                    {"Field": "Invoice Number", "Extracted Value": header.get("invoice_number") or "-"},
                    {"Field": "PO Number", "Extracted Value": header.get("po_number") or "-"},
                    {"Field": "Handwritten PO Number", "Extracted Value": header.get("handwritten_po_number") or "-"},
                    {"Field": "Invoice Date", "Extracted Value": header.get("invoice_date") or "-"},
                    {"Field": "Ship Date", "Extracted Value": header.get("ship_date") or "-"},
                    {"Field": "Due Date", "Extracted Value": header.get("due_date") or "-"},
                    {"Field": "Payment Terms", "Extracted Value": header.get("payment_terms") or "-"},
                    {"Field": "Subtotal", "Extracted Value": f"${header.get('subtotal') or 0.0:,.2f}" if header.get('subtotal') else "-"},
                    {"Field": "Tax Amount", "Extracted Value": f"${header.get('tax_amount') or 0.0:,.2f}" if header.get('tax_amount') else "-"},
                    {"Field": "Freight / Delivery Fee", "Extracted Value": f"${header.get('freight_amount') or 0.0:,.2f}" if header.get('freight_amount') else "-"},
                    {"Field": "Invoice Total", "Extracted Value": f"${header.get('invoice_total') or 0.0:,.2f}" if header.get('invoice_total') else "-"},
                    {"Field": "Handwritten Notes", "Extracted Value": header.get("handwritten_notes") or "-"},
                ]
                st.table(pd.DataFrame(header_display))

            with tab_json:
                st.json(extracted)
