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
# Authentication Guard Screen
# -------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.markdown("## 🔒 Purchase Invoice Automation — Dashboard Login")
    st.markdown("Please enter your authorized dashboard password to manage keys and process purchase orders.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        pwd = st.text_input("Dashboard Password", type="password", key="login_password_input")
        if st.button("Unlock Dashboard", type="primary", use_container_width=True):
            if login_user(pwd):
                st.success("Authenticated successfully!")
                st.rerun()
            else:
                st.error("Invalid dashboard password. Please try again.")
    st.stop()


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
st.markdown("### 📤 Upload Purchase Invoices & Delivery Manifests")
uploaded_files = st.file_uploader(
    "Upload one or multiple PDF / image invoices",
    type=["pdf", "png", "jpg", "jpeg", "tiff", "txt"],
    accept_multiple_files=True,
    help="Supports multi-page supplier invoices, scanned receipts, and manifests from any distributor."
)

if uploaded_files:
    st.info(f"📁 **{len(uploaded_files)} file(s) ready for extraction.**")
    
    if st.button("⚡ Extract Invoices", type="primary", use_container_width=True):
        progress_bar = st.progress(0)
        status_box = st.empty()

        for idx, up_file in enumerate(uploaded_files):
            file_num = idx + 1
            progress_pct = int((idx / len(uploaded_files)) * 100)
            progress_bar.progress(progress_pct)
            status_box.markdown(f"⏳ **Processing file {file_num}/{len(uploaded_files)}: `{up_file.name}`...**")

            try:
                # Post file to FastAPI endpoint
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
        status_box.success("🎉 Extraction processing complete for all documents!")
        st.rerun()


# =============================================================
# Section 2: Extraction Results Display
# =============================================================
if st.session_state["extractions"]:
    st.markdown("---")
    st.markdown("### 📊 Extracted Invoice Reports")

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        if st.button("🧹 Clear All Results"):
            st.session_state["extractions"] = []
            st.rerun()

    for item_idx, item in enumerate(st.session_state["extractions"]):
        fname = item["filename"]
        is_succ = item["success"]

        if not is_succ:
            with st.expander(f"❌ {fname} — Extraction Failed", expanded=True):
                st.error(f"Failed to extract '{fname}': {item.get('error', 'Unknown error')}")
                st.caption("Tip: Ensure the document contains readable line items or check provider API limits.")
            continue

        resp_data = item["data"]
        extracted = resp_data.get("extracted_data", {})
        header = extracted.get("header", {})
        line_items = extracted.get("line_items", [])
        validation = extracted.get("validation", {})
        detected_headers = extracted.get("detected_table_headers", [])
        download_url = resp_data.get("download_excel_url", "")
        file_id = resp_data.get("file_id", "")
        provider_used = resp_data.get("provider_used", "Mistral AI")
        status_flag = resp_data.get("status", "success")

        # Title with validation badge
        is_valid = validation.get("is_valid", False)
        title_icon = "✅" if is_valid else "⚠️"
        expander_title = f"{title_icon} {fname} — {header.get('vendor_name') or 'Invoice'} (Total: ${header.get('invoice_total') or 0.0:,.2f})"

        with st.expander(expander_title, expanded=True):
            # Top row badges
            col_b1, col_b2, col_b3 = st.columns([2, 2, 2])
            with col_b1:
                st.markdown(f"<div class='provider-chip'>⚡ Extracted via: <b>{provider_used}</b></div>", unsafe_allow_html=True)
            with col_b2:
                if is_valid:
                    st.success("✓ Math Cross-Check Passed (100% Verified)")
                else:
                    st.error("✖ Math Discrepancy or Missing Totals Detected")
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
                    st.caption(f"Excel link: [Download]({download_url})")

            # KPI Metrics Row
            m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
            with m_col1:
                st.metric("Vendor", header.get("vendor_name") or "N/A")
            with m_col2:
                st.metric("Invoice #", header.get("invoice_number") or "N/A")
            with m_col3:
                st.metric("PO #", header.get("po_number") or header.get("handwritten_po_number") or "N/A")
            with m_col4:
                st.metric("Invoice Total", f"${header.get('invoice_total') or 0.0:,.2f}")
            with m_col5:
                st.metric("Line Items", len(line_items))

            # Validation Breakdown
            if not is_valid:
                diff = validation.get("total_difference", 0.0)
                extracted_tot = validation.get("extracted_invoice_total", 0.0)
                calc_tot = validation.get("calculated_line_items_total", 0.0)
                disc_notes = validation.get("summary_notes", [])
                st.warning(
                    f"**Audit Alert**: Extracted total (${extracted_tot or 0.0:,.2f}) differs from line items sum (${calc_tot:,.2f}) by **${diff:,.2f}**.\n\n"
                    + "\n".join(f"- {n}" for n in disc_notes)
                )

            # Handwritten Notes & Margins
            hw_notes = header.get("handwritten_notes")
            if hw_notes:
                st.info(f"✍️ **Handwritten Annotations Detected on Header / Margins:**\n{hw_notes}")

            # Line Items Table
            if line_items:
                st.markdown("#### 📋 Extracted Line Items")
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

            # Raw JSON Toggle
            with st.expander("🔍 View Raw JSON"):
                st.json(extracted)


# =============================================================
# Section 3: Interactive Invoice Assistant Chatbot
# =============================================================
st.markdown("---")
st.markdown("### 💬 Invoice Assistant Chatbot")
st.caption("Ask questions about the uploaded invoices, totals, missing fields, or vendor items.")

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

# Display previous messages
for msg in st.session_state["chat_history"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_query = st.chat_input("E.g. What is the total sum across all invoices? Or list any broken items...")

if user_query:
    # Append user question
    st.session_state["chat_history"].append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    # Generate answer from current extractions
    with st.chat_message("assistant"):
        q_lower = user_query.lower()
        extractions = st.session_state.get("extractions", [])
        
        if not extractions:
            ans = "No invoices have been extracted yet. Please upload and extract an invoice PDF above, then ask me anything about it!"
        else:
            succ_exts = [e for e in extractions if e.get("success")]
            
            if "total" in q_lower or "sum" in q_lower or "overall" in q_lower:
                grand_total = sum(
                    float(e["data"].get("extracted_data", {}).get("header", {}).get("invoice_total") or 0.0)
                    for e in succ_exts
                )
                vendors = [e["data"].get("extracted_data", {}).get("header", {}).get("vendor_name") for e in succ_exts]
                ans = f"**Grand Total Across All Invoices:** **${grand_total:,.2f}** across {len(succ_exts)} document(s).\n\n"
                ans += "**Breakdown by Invoice:**\n"
                for e in succ_exts:
                    h = e["data"]["extracted_data"]["header"]
                    ans += f"- **{e['filename']}** ({h.get('vendor_name')}): **${h.get('invoice_total') or 0.0:,.2f}** (Invoice #{h.get('invoice_number')})\n"

            elif "broken" in q_lower or "short" in q_lower or "mispick" in q_lower or "refused" in q_lower or "flag" in q_lower:
                flagged = []
                for e in succ_exts:
                    for li in e["data"]["extracted_data"]["line_items"]:
                        if li.get("special_flag") or li.get("handwritten_note"):
                            flagged.append((e["filename"], li))
                if flagged:
                    ans = f"Found **{len(flagged)}** flagged / damaged / short item(s):\n"
                    for fname, li in flagged:
                        ans += f"- **{fname}** — Line {li.get('line_number')}: {li.get('description')} | Status: `{li.get('special_flag')}` | Note: *{li.get('handwritten_note')}*\n"
                else:
                    ans = "No items were flagged as broken, short, or refused across the uploaded invoices."

            elif "po" in q_lower or "purchase order" in q_lower:
                ans = "**Purchase Order Numbers Extracted:**\n"
                for e in succ_exts:
                    h = e["data"]["extracted_data"]["header"]
                    po = h.get("po_number") or h.get("handwritten_po_number") or "None"
                    ans += f"- **{e['filename']}**: PO# `{po}` (Vendor: {h.get('vendor_name')})\n"

            else:
                total_items = sum(len(e["data"]["extracted_data"]["line_items"]) for e in succ_exts)
                ans = f"Analyzed **{len(succ_exts)} uploaded invoice(s)** with a total of **{total_items} line items**.\n\n"
                ans += "You can ask for specific information like:\n"
                ans += "- *What is the grand total of all invoices?*\n"
                ans += "- *List any items that are broken, damaged, or shorted.*\n"
                ans += "- *Show all PO numbers and invoice dates.*\n"
                ans += "- *Which invoices had mathematical discrepancies?*"

        st.markdown(ans)
        st.session_state["chat_history"].append({"role": "assistant", "content": ans})
