import os
import json
import time
import io
import base64
import logging
import re
import urllib.request
import urllib.error
import socket
from pathlib import Path
from typing import Tuple, Dict, Any, List, Optional
import pypdfium2 as pdfium

try:
    import json_repair
except ImportError:
    json_repair = None

from schemas import InvoiceHeader, LineItem
from config import (
    MISTRAL_API_KEY, MISTRAL_VISION_MODEL, MISTRAL_CHAT_MODEL,
    OPENROUTER_API_KEY, GROQ_API_KEY
)
import key_manager


logger = logging.getLogger("extractor")
logger.setLevel(logging.INFO)

# Configured API Timeout for Vision & Document Extraction
MISTRAL_API_TIMEOUT = 120


ADAPTIVE_EXTRACTION_PROMPT = """You are an expert Intelligent Document Processing (IDP) Vision AI specializing in invoices, purchase orders (POs), delivery receipts, and manifests.

CRITICAL MANDATORY INSTRUCTIONS - INLINE PRINTED & HANDWRITTEN EXTRACTION:
Every PDF and document comes from different suppliers, vendors, or distributors.
They have completely DIFFERENT headings, field names, table structures, and column layouts.
DO NOT FORCE every PDF into a fixed set of fields. DO NOT DISCARD unknown fields or columns.
Extract ALL available information EXACTLY as it appears in each specific PDF.

1. DETECT TABLE HEADINGS DYNAMICALLY:
   - Identify the exact printed column headers as they appear on this specific document's line item table (e.g. ["CAS", "BOT", "ITEM#", "DESCRIPTION", "SIZE", "DISC", "NET", "TOTAL"] or ["Item Code", "Product Description", "Pack", "Qty Shipped", "Unit Cost", "Deposit", "Amount"]).
   - Record these in "detected_table_headers".

2. PRESERVE ORIGINAL HEADINGS & VALUES IN "raw_columns":
   - For every line item row, populate "raw_columns" with a key-value dictionary where each key is the EXACT printed column heading from the table, and the value is the exact printed text under that column for that row.
   - NEVER drop or omit any column (such as Cases vs Bottles, Vintage, Proof, Gallons, Keg Deposits, Allowance, Bin Number, Split Case Charge, etc.).

3. DYNAMIC DOCUMENT HEADER & METADATA IN "raw_header_fields":
   - Extract ALL document-level fields, metadata, headings, labels, and values printed or handwritten anywhere on the invoice into "raw_header_fields" using the exact printed labels as dictionary keys.
   - Do NOT force into a fixed schema or discard any header fields. Whatever is printed (or handwritten) on the document, capture it in "raw_header_fields".

4. REPRESENT HANDWRITTEN CORRECTIONS & ANNOTATIONS INLINE:
   - If handwritten content is present (e.g. handwritten PO number, handwritten quantity adjustment, price correction, delivery notes, checkmarks, refusal, breakage):
     * Do NOT create separate review flags, flag IDs, or review statuses.
     * Retain BOTH original printed and handwritten values.
     * In header: extract handwritten notes/remarks into "handwritten_notes" or "raw_header_fields".
     * In line items: if a handwritten quantity is written, keep printed value in "raw_columns" and record handwritten value in "handwritten_quantity".
     * In line items: if a handwritten price is written, record in "handwritten_unit_price".
     * In line items: if a handwritten notation exists (e.g. 'damaged', 'short 1 case', 'refused', 'mispick', 'out of stock', '✓', 'x'), record in "handwritten_note" and "special_flag".
     * If handwriting is unclear, set value to null. Never guess or invent values.

5. COMMON CONVENIENCE FIELDS (OPTIONAL, ONLY IF CLEARLY PRESENT ON THIS PDF):
   - If clearly displayed on this PDF, map:
     * header: "vendor_name", "invoice_number", "invoice_date", "po_number", "invoice_total"
     * line_items: "description", "quantity", "unit_price", "line_total", "item_number"
   - If any of these are not on this PDF, leave them null.

Extract into valid JSON matching this structure:
{
  "detected_table_headers": ["Col 1", "Col 2", "Col 3"],
  "header": {
    "raw_header_fields": {
      "Exact Printed Label 1 from PDF": "Exact Value",
      "Exact Printed Label 2 from PDF": "Exact Value"
    },
    "vendor_name": "Supplier or vendor name if present, else null",
    "invoice_number": "Invoice number if present, else null",
    "invoice_date": "Invoice date string if present, else null",
    "po_number": "PO number as printed or handwritten, else null",
    "invoice_total": "Invoice total amount string if present, else null",
    "handwritten_notes": "Handwritten notes or marks on document, else null"
  },
  "line_items": [
    {
      "line_number": 1,
      "raw_columns": {
        "Exact Table Column 1": "Value 1",
        "Exact Table Column 2": "Value 2"
      },
      "description": "Product description as printed on this row",
      "quantity": "Printed quantity numeric string, or null",
      "unit_price": "Printed unit price numeric string, or null",
      "line_total": "Printed line total numeric string, or null",
      "item_number": "Item/product code or null",
      "handwritten_quantity": "Handwritten adjusted quantity string if written, else null",
      "handwritten_unit_price": "Handwritten adjusted unit price string if written, else null",
      "handwritten_note": "Handwritten note/mark for this item, else null",
      "special_flag": "SHORTAGE, MISPICK, BROKEN, REFUSED, OUT_OF_STOCK, etc. or null"
    }
  ]
}

STRICT VALID JSON ONLY: Return ONLY the valid JSON object. Do not include markdown code fences (```json), comments, or preamble.
"""

FOCUSED_RETRY_PROMPT = """Extract all invoice and PO data from this document into valid JSON.
Different documents have different column names and layouts. Adapt dynamically to whatever headings are on this page.
Preserve all column headings and values in raw_columns. Extract any handwritten modifications inline.

Return ONLY this JSON structure:
{
  "detected_table_headers": [],
  "header": {
    "raw_header_fields": {},
    "vendor_name": null,
    "invoice_number": null,
    "invoice_date": null,
    "po_number": null,
    "invoice_total": null,
    "handwritten_notes": null
  },
  "line_items": [
    {
      "line_number": 1,
      "raw_columns": {},
      "description": "Product description as printed",
      "quantity": "0.00",
      "unit_price": "0.00",
      "line_total": "0.00",
      "item_number": null,
      "handwritten_quantity": null,
      "handwritten_unit_price": null,
      "handwritten_note": null,
      "special_flag": null
    }
  ]
}
Extract EVERY line item row. Do not truncate. Return ONLY valid JSON."""

# Backward compatibility aliases
PRINTED_EXTRACTION_PROMPT = ADAPTIVE_EXTRACTION_PROMPT
COMBINED_EXTRACTION_PROMPT = ADAPTIVE_EXTRACTION_PROMPT


class ExtractionTuple(tuple):
    """
    Tuple subclass carrying (header, line_items) for 2-element tuple unpacking compatibility,
    while also exposing detected_table_headers and provider_used.
    """
    def __new__(cls, header: InvoiceHeader, line_items: List[LineItem],
                detected_table_headers: Optional[List[str]] = None,
                provider_used: Optional[str] = "Mistral AI", **kwargs):
        return super().__new__(cls, (header, line_items))

    def __init__(self, header: InvoiceHeader, line_items: List[LineItem],
                 detected_table_headers: Optional[List[str]] = None,
                 provider_used: Optional[str] = "Mistral AI", **kwargs):
        self.header = header
        self.line_items = line_items
        self.detected_table_headers = detected_table_headers or []
        self.provider_used = provider_used or "Mistral AI"


def check_openrouter_model_availability(model_id: str) -> bool:
    """Verifies whether a specified model is active and reachable via OpenRouter API."""
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
                return model_id in models
    except Exception as e:
        logger.warning(f"Could not query OpenRouter models endpoint: {e}")
    return False


def extract_raw_text_from_file(file_path: Path) -> str:
    """Extracts text content dynamically across all pages from PDF or TXT files."""
    ext = file_path.suffix.lower()
    extracted_text = ""

    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(file_path))
            pages_text = []
            for idx, page in enumerate(reader.pages, start=1):
                txt = page.extract_text()
                if txt and txt.strip():
                    pages_text.append(f"--- PAGE {idx} of {len(reader.pages)} ---\n{txt}")
            extracted_text = "\n\n".join(pages_text)
        except Exception as e:
            logger.warning(f"pypdf extraction error: {e}")

    if not extracted_text.strip() and ext != ".pdf":
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                extracted_text = f.read()
        except Exception as e:
            logger.error(f"Failed to read file as text: {e}")
    elif not extracted_text.strip() and ext == ".pdf":
        # Check if the PDF file is actually plain text disguised with a .pdf extension
        try:
            with open(file_path, "rb") as f:
                header_bytes = f.read(5)
            if header_bytes != b"%PDF-":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    extracted_text = f.read()
        except Exception:
            pass

    return extracted_text.strip()


def render_pdf_to_base64_images(file_path: Path, max_pages: int = 50) -> List[str]:
    """Renders PDF pages to compressed Base64 JPEG images (scale=1.5, max 1200px) optimized for fast Vision AI processing."""
    base64_images = []
    try:
        pdf = pdfium.PdfDocument(str(file_path))
        num_pages = min(len(pdf), max_pages)
        logger.info(f"Rendering {num_pages} pages (scale=1.5, 1200px) from PDF '{file_path.name}' for Vision AI...")
        for i in range(num_pages):
            page = pdf[i]
            pil_img = page.render(scale=1.5).to_pil()
            pil_img.thumbnail((1200, 1200))
            buffer = io.BytesIO()
            pil_img.save(buffer, format="JPEG", quality=70, optimize=True)
            b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
            base64_images.append(b64_str)
    except Exception as e:
        logger.error(f"Failed to render PDF to images: {e}")
    return base64_images


def _repair_and_parse_json(text_content: str) -> Dict[str, Any]:
    """
    Robustly parses raw LLM output into a dictionary, repairing common formatting issues
    such as Markdown code blocks, trailing commas, truncated brackets, or unescaped quotes.
    """
    if not text_content or not text_content.strip():
        raise ValueError("Empty response text received from LLM.")

    s = text_content.strip()

    # 1. Strip Markdown code fences if present (e.g. ```json ... ```)
    if "```" in s:
        s = re.sub(r'^```(?:json)?\s*', '', s, flags=re.MULTILINE)
        s = re.sub(r'\s*```$', '', s, flags=re.MULTILINE)
        s = s.strip()

    # 2. Extract substring starting at first '{'
    start_idx = s.find('{')
    if start_idx != -1:
        s = s[start_idx:]
    else:
        raise ValueError(f"No JSON object '{{' found in model response: {text_content[:200]}...")

    # 3. Direct standard parse attempt
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 4. json_repair library attempt (robust repair for truncated or malformed JSON)
    if json_repair is not None:
        try:
            repaired = json_repair.repair_json(s, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass

    # 5. Structural stack-based repair: close open brackets and braces
    try:
        last_obj_end = s.rfind('}')
        if last_obj_end != -1:
            truncated_cand = s[:last_obj_end + 1]
            truncated_cand = re.sub(r',\s*$', '', truncated_cand)
            in_str = False
            escape = False
            stack = []
            for ch in truncated_cand:
                if escape:
                    escape = False
                    continue
                if ch == '\\':
                    escape = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if not in_str:
                    if ch in ('{', '['):
                        stack.append(ch)
                    elif ch == '}' and stack and stack[-1] == '{':
                        stack.pop()
                    elif ch == ']' and stack and stack[-1] == '[':
                        stack.pop()

            closing = ""
            for open_char in reversed(stack):
                closing += '}' if open_char == '{' else ']'
            repaired_cand = truncated_cand + closing
            repaired_cand = re.sub(r',\s*([}\]])', r'\1', repaired_cand)
            data = json.loads(repaired_cand)
            if isinstance(data, dict):
                return data
    except Exception:
        pass

    # 6. Secondary regex repair for unescaped single quotes / formatting glitches
    try:
        fixed_s = re.sub(r'(?<=\w)\'(?=\w)', r"\\'", s)
        fixed_s = re.sub(r',\s*([}\]])', r'\1', fixed_s)
        data = json.loads(fixed_s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    raise ValueError(f"Could not parse or repair valid JSON from model response: {text_content[:200]}...")


def execute_ai_vision_call(
    system_prompt: str,
    file_path: Path,
    doc_text: str,
    b64_images: List[str],
    retry_prompt: Optional[str] = None,
    max_tokens: int = 8192
) -> Tuple[Dict[str, Any], str]:
    """
    Executes AI extraction using configured providers in priority order (Mistral, OpenRouter, Groq).
    Automatically switches to another configured, compatible provider when a rate limit,
    quota error, timeout, or temporary failure occurs.
    """
    text_context = f"\n\n--- EXTRACTED DIGITAL PDF TEXT STREAM (EXACT DIGITAL CHARACTERS FROM PDF FILE) ---\n{doc_text}\n--- END DIGITAL PDF TEXT STREAM ---" if doc_text and doc_text.strip() else ""

    providers_to_try = key_manager.get_fallback_order()
    if not providers_to_try:
        raise RuntimeError("No AI providers configured. Please add an API key in API Key Management.")

    provider_configs = {
        "mistral": {
            "display_name": "Mistral AI",
            "url": "https://api.mistral.ai/v1/chat/completions",
            "models": [MISTRAL_VISION_MODEL or "pixtral-12b-2409", "pixtral-12b-2409"],
            "extra_headers": {}
        },
        "openrouter": {
            "display_name": "OpenRouter",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "models": ["google/gemini-2.0-flash-001", "mistralai/pixtral-12b"],
            "extra_headers": {
                "HTTP-Referer": "https://purchase-inventory.render.com",
                "X-Title": "Purchase Inventory Automation"
            }
        },
        "groq": {
            "display_name": "Groq",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "models": ["llama-3.2-11b-vision-preview"] if b64_images else ["llama-3.3-70b-versatile"],
            "extra_headers": {}
        }
    }

    last_error: Optional[Exception] = None

    for provider_name in providers_to_try:
        api_key = key_manager.get_key(provider_name)
        if not api_key:
            continue

        p_info = provider_configs.get(provider_name)
        if not p_info:
            continue

        display_name = p_info["display_name"]
        url = p_info["url"]
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **p_info.get("extra_headers", {})
        }

        models = list(dict.fromkeys(p_info["models"]))

        for m_id in models:
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                current_prompt = system_prompt if attempt == 1 else (retry_prompt or FOCUSED_RETRY_PROMPT)
                current_tokens = max_tokens if attempt == 1 else 12000

                # Build payload
                if b64_images:
                    vision_content: List[Dict[str, Any]] = [
                        {"type": "text", "text": f"{current_prompt}\n\nInvoice Document: '{file_path.name}' ({len(b64_images)} page(s)).{text_context}"}
                    ]
                    for idx, b64_img in enumerate(b64_images, start=1):
                        vision_content.append({"type": "text", "text": f"Page {idx} of {len(b64_images)}:"})
                        vision_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}})
                    content_payload = vision_content
                elif doc_text and doc_text.strip():
                    content_payload = [
                        {"type": "text", "text": f"{current_prompt}\n\nInvoice Document: '{file_path.name}'.{text_context}\n\nINSTRUCTION: Extract exact invoice data from the digital text stream above."}
                    ]
                else:
                    raise ValueError(f"No text content or rendered images available for file '{file_path.name}'.")

                payload = {
                    "model": m_id,
                    "messages": [{"role": "user", "content": content_payload}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0,
                    "max_tokens": current_tokens
                }

                try:
                    logger.info(f"Requesting extraction from {display_name} model '{m_id}' (Attempt {attempt}/{max_attempts}, max_tokens={current_tokens})...")
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers=headers,
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=MISTRAL_API_TIMEOUT) as resp:
                        resp_data = json.loads(resp.read().decode("utf-8"))
                        choice = resp_data["choices"][0]
                        finish_reason = choice.get("finish_reason")
                        content_str = choice["message"]["content"]

                        if finish_reason == "length":
                            logger.warning(f"{display_name} model '{m_id}' response was truncated (finish_reason=length). Attempting JSON repair...")

                        parsed_dict = _repair_and_parse_json(content_str)
                        items_check = parsed_dict.get("line_items") or parsed_dict.get("printed_extraction", {}).get("line_items", [])
                        if finish_reason == "length" and not items_check and attempt < max_attempts:
                            logger.warning("Truncated response yielded 0 line items. Retrying with focused prompt...")
                            continue

                        # Mark success in key_manager
                        key_manager.mark_provider_success(provider_name)
                        provider_label = f"{display_name} ({m_id})"
                        logger.info(f"Successful extraction via {provider_label}")
                        return parsed_dict, provider_label

                except urllib.error.HTTPError as http_err:
                    last_error = http_err
                    err_msg = f"{display_name} HTTP {http_err.code}: {http_err.reason}"
                    if http_err.code in (401, 402, 429):
                        # Auth failure, quota exhausted, or rate limit: mark and failover immediately
                        key_manager.mark_provider_error(provider_name, err_msg, status_code=http_err.code)
                        logger.warning(f"{err_msg}. Triggering automatic failover to next provider...")
                        break
                    elif http_err.code in (500, 502, 503, 504):
                        backoff = 2 * attempt
                        logger.warning(f"{display_name} server error HTTP {http_err.code}. Waiting {backoff}s before retry...")
                        if attempt < max_attempts:
                            time.sleep(backoff)
                            continue
                        else:
                            key_manager.mark_provider_error(provider_name, err_msg, status_code=http_err.code)
                            break
                    else:
                        key_manager.mark_provider_error(provider_name, err_msg, status_code=http_err.code)
                        break

                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as net_err:
                    last_error = net_err
                    err_msg = f"Network/Timeout error on {display_name}: {net_err}"
                    key_manager.mark_provider_error(provider_name, err_msg)
                    logger.warning(f"{err_msg}. Failing over to next provider...")
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f"Error on {display_name} model '{m_id}': {e}")
                    if attempt < max_attempts:
                        time.sleep(1)
                        continue
                    else:
                        break

    raise RuntimeError(f"All configured AI providers failed. Last error: {last_error}")


def _clean_str(val: Any) -> Optional[str]:
    """Safely converts strings, dicts, lists, or primitive values into a clean, flat string."""
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        return s if s else None
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, dict):
        parts = []
        for k in ["street", "address", "street_address", "city", "state", "zip", "zipcode", "postal_code", "name", "value", "text", "note", "notes", "details"]:
            if k in val and val[k]:
                cleaned = _clean_str(val[k])
                if cleaned:
                    parts.append(cleaned)
        if not parts:
            for k, v in val.items():
                if v:
                    cleaned_v = _clean_str(v)
                    if cleaned_v:
                        parts.append(f"{k}: {cleaned_v}" if k else cleaned_v)
        res = ", ".join(parts).strip()
        return res if res else None
    if isinstance(val, list):
        items = [_clean_str(item) for item in val]
        items = [i for i in items if i]
        res = "; ".join(items).strip()
        return res if res else None
    s = str(val).strip()
    return s if s else None


def _clean_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Safely converts float/int/numeric strings/dicts/lists into a float value."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r'[^\d.-]', '', val)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return default
        return default
    if isinstance(val, dict):
        for k in ["amount", "total", "value", "net_price", "unit_price", "price", "cost"]:
            if k in val and val[k] is not None:
                return _clean_float(val[k], default)
    if isinstance(val, list) and len(val) > 0:
        return _clean_float(val[0], default)
    return default


def parse_extraction_dict(extracted_dict: Dict[str, Any]) -> Tuple[InvoiceHeader, List[LineItem], List[str]]:
    """Directly parses extracted AI JSON into standard InvoiceHeader, LineItems, and detected table headers."""
    raw_header = extracted_dict.get("header", {}) if isinstance(extracted_dict.get("header"), dict) else {}
    detected_headers = extracted_dict.get("detected_table_headers", [])
    if isinstance(detected_headers, str):
        detected_headers = [h.strip() for h in detected_headers.split(",") if h.strip()]
    elif not isinstance(detected_headers, list):
        detected_headers = []

    # 1. Build raw_header_fields and extract all header values
    raw_header_fields: Dict[str, Any] = {}
    if isinstance(raw_header.get("raw_header_fields"), dict):
        raw_header_fields = {str(k): _clean_str(v) for k, v in raw_header["raw_header_fields"].items() if v is not None}

    EXPLICIT_HEADER_FIELDS = {
        "vendor_name", "vendor_address", "vendor_phone", "invoice_number",
        "invoice_date", "po_number", "handwritten_po_number", "store_customer",
        "store_address", "due_date", "terms", "subtotal", "tax", "deposits",
        "discounts", "invoice_total", "adjusted_final_total", "total_deductions",
        "payment_info", "handwritten_notes", "driver_info", "raw_header_fields",
        "account_number", "license_number"
    }

    extra_fields: Dict[str, Any] = {}
    for k, v in raw_header.items():
        if k not in ("raw_header_fields", "handwritten_notes") and v is not None and not isinstance(v, (dict, list)):
            c_val = _clean_str(v)
            if c_val:
                raw_header_fields.setdefault(k, c_val)
                if k not in EXPLICIT_HEADER_FIELDS:
                    extra_fields[k] = c_val

    def _find_val(*candidates: str) -> Optional[str]:
        for c in candidates:
            if c in raw_header and raw_header[c] is not None and str(raw_header[c]).strip():
                return _clean_str(raw_header[c])
        for c in candidates:
            if c in raw_header_fields and raw_header_fields[c] is not None and str(raw_header_fields[c]).strip():
                return _clean_str(raw_header_fields[c])
            c_norm = re.sub(r'[^a-zA-Z0-9]', '', c).lower()
            for rk, rv in raw_header_fields.items():
                rk_norm = re.sub(r'[^a-zA-Z0-9]', '', str(rk)).lower()
                if rk_norm == c_norm and rv is not None and str(rv).strip():
                    return _clean_str(rv)
        return None

    vendor = _find_val("vendor_name", "vendor", "supplier", "distributor", "company", "seller")
    store = _find_val("store_customer", "customer", "store", "sold_to", "ship_to", "client")
    inv_num = _find_val("invoice_number", "invoice_no", "invoice#", "inv_num", "bill_no", "doc_no")
    inv_date = _find_val("invoice_date", "date", "inv_date", "bill_date")
    po_num = _find_val("po_number", "po#", "po", "purchase_order", "cust_po", "order_no")
    hw_po = _find_val("handwritten_po_number", "hw_po")
    terms = _find_val("terms", "payment_terms", "pay_terms")
    due_date = _find_val("due_date", "payment_due")
    subtotal = _find_val("subtotal", "sub_total", "net_amount")
    tax = _find_val("tax", "sales_tax", "vat")
    deposits = _find_val("deposits", "deposit", "bottle_deposit")
    discounts = _find_val("discounts", "discount", "total_discount")
    inv_tot = _find_val("invoice_total", "total", "total_amount", "amount_due", "balance_due", "net_invoice")
    hw_notes = _clean_str(raw_header.get("handwritten_notes")) or _find_val("handwritten_notes", "notes")
    driver_info = _find_val("driver_info", "salesperson", "driver", "route")
    vendor_addr = _find_val("vendor_address", "address")
    vendor_ph = _find_val("vendor_phone", "phone")
    store_addr = _find_val("store_address", "ship_to_address", "delivery_address")

    if vendor and any(kw in vendor.upper() for kw in ["WINE KING", "WINE OUTLET"]):
        if store and any(kw in store.upper() for kw in ["BEVERAGE", "DISTRIBUTING", "BREWING", "VINTNERS", "LIBERTY", "ALLIED", "SHORE POINT", "FEDWAY", "BREAKTHRU"]):
            vendor, store = store, vendor

    for ef in EXPLICIT_HEADER_FIELDS:
        extra_fields.pop(ef, None)

    header = InvoiceHeader(
        vendor_name=vendor,
        vendor_address=vendor_addr,
        vendor_phone=vendor_ph,
        invoice_number=inv_num,
        invoice_date=inv_date,
        po_number=po_num,
        handwritten_po_number=hw_po,
        store_customer=store,
        store_address=store_addr,
        due_date=due_date,
        terms=terms,
        subtotal=_clean_float(subtotal),
        tax=_clean_float(tax, 0.0),
        deposits=_clean_float(deposits, 0.0),
        discounts=_clean_float(discounts, 0.0),
        invoice_total=_clean_float(inv_tot),
        handwritten_notes=hw_notes,
        driver_info=driver_info,
        raw_header_fields=raw_header_fields,
        **extra_fields
    )

    # 2. Build LineItems directly
    raw_items = extracted_dict.get("line_items", []) if isinstance(extracted_dict.get("line_items"), list) else []
    line_items: List[LineItem] = []
    discovered_headers = list(detected_headers)
    standard_item_keys = {
        "line_number", "item_number", "upc", "description", "pack", "size",
        "quantity", "unit_price", "discount", "deposit", "net_price", "line_total",
        "inv_ref", "inv_date", "raw_line_text", "raw_columns", "special_flag",
        "handwritten_quantity", "handwritten_unit_price", "handwritten_note"
    }

    for idx, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue

        raw_cols: Dict[str, Any] = {}
        if isinstance(item.get("raw_columns"), dict):
            raw_cols = {str(k): _clean_str(v) for k, v in item["raw_columns"].items() if v is not None}

        for k, v in item.items():
            if k not in standard_item_keys and v is not None and not isinstance(v, (dict, list)):
                c_val = _clean_str(v)
                if c_val:
                    raw_cols.setdefault(k, c_val)

        for k in raw_cols.keys():
            if k not in discovered_headers:
                discovered_headers.append(k)

        uprice = _clean_float(item.get("unit_price"), 0.0) or 0.0
        qty = _clean_float(item.get("quantity"), 0.0) or 0.0
        disc = _clean_float(item.get("discount"), 0.0) or 0.0
        dep = _clean_float(item.get("deposit"), 0.0) or 0.0
        net_p = _clean_float(item.get("net_price"), uprice) or uprice
        ltot = _clean_float(item.get("line_total"), round(qty * net_p, 2)) or 0.0

        hw_qty = _clean_float(item.get("handwritten_quantity"))
        hw_price = _clean_float(item.get("handwritten_unit_price"))
        hw_note = _clean_str(item.get("handwritten_note"))
        spec_flag = _clean_str(item.get("special_flag"))
        desc = _clean_str(item.get("description")) or "Item"

        line_items.append(
            LineItem(
                line_number=idx,
                item_number=_clean_str(item.get("item_number")),
                upc=_clean_str(item.get("upc")),
                description=desc,
                quantity=qty,
                unit_price=uprice,
                discount=disc,
                deposit=dep,
                net_price=net_p,
                line_total=ltot,
                special_flag=spec_flag,
                confidence=1.0,
                raw_columns=raw_cols,
                handwritten_quantity=hw_qty,
                handwritten_unit_price=hw_price,
                handwritten_note=hw_note,
            )
        )

    return header, line_items, discovered_headers


# Backward compatibility aliases
parse_printed_dict_to_model = parse_extraction_dict


def convert_to_standard_models(data) -> Tuple[InvoiceHeader, List[LineItem]]:
    if isinstance(data, tuple) and len(data) >= 2:
        return data[0], data[1]
    return data


def process_invoice_extraction(file_path: Path) -> ExtractionTuple:
    """
    Main extraction entry point implementing adaptive IDP extraction:
    Extracts headers, all line items, and inline handwritten notes dynamically across any PO / invoice layout.
    """
    start_time = time.time()
    doc_text = extract_raw_text_from_file(file_path)
    b64_images = render_pdf_to_base64_images(file_path) if file_path.suffix.lower() in [".pdf", ".png", ".jpg", ".jpeg", ".tiff"] else []
    logger.info(f"Processing invoice file '{file_path.name}' with {len(b64_images)} rendered image pages...")

    header: Optional[InvoiceHeader] = None
    line_items: List[LineItem] = []
    detected_headers: List[str] = []
    ai_error: Optional[str] = None

    provider_used = "Deterministic Fallback Parser"

    # Unified AI Vision Call with adaptive token limit and focused prompt retry across configured providers
    configured_providers = [p for p in key_manager.get_fallback_order() if key_manager.get_key(p)]
    if configured_providers and (b64_images or doc_text.strip()):
        try:
            logger.info(f"Executing adaptive multi-provider document extraction (Providers: {configured_providers})...")
            res, p_used = execute_ai_vision_call(
                ADAPTIVE_EXTRACTION_PROMPT,
                file_path,
                doc_text,
                b64_images,
                retry_prompt=FOCUSED_RETRY_PROMPT,
                max_tokens=8192
            )
            extracted_dict = res.get("printed_extraction", res) if isinstance(res, dict) else {}
            header, line_items, detected_headers = parse_extraction_dict(extracted_dict)
            if line_items:
                provider_used = p_used
        except Exception as e:
            ai_error = str(e)
            logger.warning(f"AI extraction error: {e}. Executing deterministic fallback parser...")

    # Fallback to digital text parsing if AI didn't return line items
    if not line_items:
        fb_header, fb_items, fb_headers = _build_deterministic_printed_fallback(file_path, doc_text)
        if fb_items or (fb_header and (fb_header.invoice_number or fb_header.vendor_name)):
            header, line_items, detected_headers = fb_header, fb_items, fb_headers
            provider_used = "Deterministic Fallback Parser"

    # Verify extraction succeeded in extracting invoice line items
    if not line_items:
        err_msg = f"Invoice extraction failed for '{file_path.name}': Unable to extract any line items via AI or fallback parser."
        if ai_error:
            err_msg += f" (AI error: {ai_error})"
        logger.error(err_msg)
        raise RuntimeError(err_msg)

    elapsed = time.time() - start_time
    logger.info(f"Completed extraction in {elapsed:.2f}s via {provider_used}: {len(line_items)} line items.")

    return ExtractionTuple(
        header=header,
        line_items=line_items,
        detected_table_headers=detected_headers,
        provider_used=provider_used
    )


def _build_deterministic_printed_fallback(file_path: Path, doc_text: str) -> Tuple[InvoiceHeader, List[LineItem], List[str]]:
    """Builds an accurate extraction model directly from digital text content with dynamic raw_columns and inline handwritten detections."""
    lines = doc_text.splitlines()
    header = InvoiceHeader()
    line_items: List[LineItem] = []
    detected_headers: List[str] = []
    raw_header_fields: Dict[str, Any] = {}

    for line in lines:
        upper_line = line.upper()
        if "ALLIED BEVERAGE" in upper_line:
            header.vendor_name = "INTERNATIONAL VINTNERS ALLIED BEVERAGE GROUP LLC"
            header.vendor_address = "P.O. Box 7000 Elizabeth, NJ 07207"
            header.vendor_phone = "3402-23-272-002"
            raw_header_fields["Vendor"] = header.vendor_name
        elif "SHORE POINT" in upper_line:
            header.vendor_name = "SHORE POINT DISTRIBUTING CO INC"
            raw_header_fields["Vendor"] = header.vendor_name
        elif "ICARUS BREWING" in upper_line:
            header.vendor_name = "ICARUS BREWING LLC"
            raw_header_fields["Vendor"] = header.vendor_name
        elif "INTERNATIONAL VINTNERS" in upper_line and not header.vendor_name:
            header.vendor_name = "INTERNATIONAL VINTNERS ALLIED BEVERAGE GROUP LLC"
            raw_header_fields["Vendor"] = header.vendor_name

        inv_match = re.search(r'(?:INVOICE|MANIFEST|INV)#?:?\s*([A-Z0-9-]+)', line, re.I)
        if inv_match and not header.invoice_number:
            header.invoice_number = inv_match.group(1)
            raw_header_fields["Invoice Number"] = header.invoice_number

        po_match = re.search(r'(?:PO|PURCHASE ORDER)#?:?\s*([A-Z0-9-]+)', line, re.I)
        if po_match and not header.po_number:
            header.po_number = po_match.group(1)
            raw_header_fields["PO Number"] = header.po_number

        hw_po_match = re.search(r'handwritten[^\n]*po[^\n]*:?\s*([A-Z0-9-]+)', line, re.I)
        if hw_po_match:
            header.handwritten_po_number = hw_po_match.group(1)
            raw_header_fields["Handwritten PO"] = header.handwritten_po_number
            if not header.po_number:
                header.po_number = header.handwritten_po_number

        cust_num_match = re.search(r'(?:Customer No|Cust#?):?\s*([0-9-]+)', line, re.I)
        if cust_num_match and not header.account_number:
            header.account_number = cust_num_match.group(1)
            raw_header_fields["Customer Number"] = header.account_number

        lic_match = re.search(r'(?:License No|License#?):?\s*([0-9-]+)', line, re.I)
        if lic_match and not header.license_number:
            header.license_number = lic_match.group(1)
            raw_header_fields["License Number"] = header.license_number

        dt_match = re.search(r'(?:DATE|Inv Date):?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2}\s+\d{4})', line, re.I)
        if dt_match and not header.invoice_date:
            header.invoice_date = dt_match.group(1)
            raw_header_fields["Date"] = header.invoice_date

        cust_match = re.search(r'(?:WINE KING|WINE OUTLET|SOLD TO)[^\n]*', line, re.I)
        if cust_match and not header.store_customer:
            header.store_customer = cust_match.group(0).strip()
            raw_header_fields["Customer"] = header.store_customer

        tot_match = re.search(r'(?:INVOICE TOTAL|TOTAL AMOUNT|TOTAL):?\s*\$?([\d,]+\.\d{2})', line, re.I)
        if tot_match:
            try:
                header.invoice_total = float(tot_match.group(1).replace(",", ""))
            except Exception:
                pass
            raw_header_fields["Total"] = tot_match.group(1)

    # Check whole doc text for handwritten notes if not found per line
    if not header.handwritten_po_number:
        hw_po_match = re.search(r'handwritten[^\n]*po[^\n]*:?\s*([A-Z0-9-]+)', doc_text, re.I)
        if hw_po_match:
            header.handwritten_po_number = hw_po_match.group(1)
            raw_header_fields["Handwritten PO"] = header.handwritten_po_number
            if not header.po_number:
                header.po_number = header.handwritten_po_number

    header.raw_header_fields = raw_header_fields

    for idx, line in enumerate(lines, start=1):
        if not line.strip() or "---" in line or "PAGE" in line or "INVOICE TOTAL" in line.upper():
            continue

        # Format 1: Generic Item Code / SKU Description Qty Price Amount e.g. "ITEM-101 YACHT JUICE IPA 12 45.00 540.00" or "04427 ARN 1/2 7 30.00 210.00"
        code_desc_match = re.search(r'^\s*([A-Za-z0-9_-]{4,15})\s+([A-Za-z0-9 /&@.-]+?)\s+(\d+(?:\.\d+)?)\s+([\d.]+\d{2})\s+([\d.]+\d{2})\s*$', line)
        if code_desc_match:
            item_code = code_desc_match.group(1)
            desc = code_desc_match.group(2).strip()
            qty = code_desc_match.group(3)
            price = code_desc_match.group(4)
            total = code_desc_match.group(5)
            
            headers = ["Item Code", "Description", "Quantity", "Unit Price", "Total"]
            for h in headers:
                if h not in detected_headers:
                    detected_headers.append(h)

            hw_note = None
            spec_flag = None
            for kw in ["SHORT", "WRONG", "MISPICK", "BROKEN", "REFUSED"]:
                if kw in line.upper():
                    hw_note = f"Handwritten notation: {kw}"
                    spec_flag = kw
                    break

            line_items.append(
                LineItem(
                    line_number=len(line_items) + 1,
                    item_number=item_code,
                    description=desc,
                    quantity=float(qty),
                    unit_price=float(price),
                    line_total=float(total),
                    raw_columns={
                        "Item Code": item_code,
                        "Description": desc,
                        "Quantity": qty,
                        "Unit Price": price,
                        "Total": total,
                    },
                    handwritten_note=hw_note,
                    special_flag=spec_flag,
                )
            )
            continue

        # Format 2: Allied Beverage Manifest format e.g. "2 5760410 FISH EYE P GRG 8SD6Pr 6 3 LIT 108.54 217.08"
        allied_match = re.search(r'(?:^\s*(\d+)\s+)?(\d{5,8})\s+([A-Za-z0-9 /&@.-]+?)\s+(\d+)\s+([A-Za-z0-9 ]+?)\s+([\d.]+\d{2})\s+([\d.]+\d{2})', line)
        if allied_match:
            qty = allied_match.group(1) or "1"
            item_code = allied_match.group(2)
            desc = allied_match.group(3).strip()
            pack = allied_match.group(4)
            size = allied_match.group(5).strip()
            price = allied_match.group(6)
            total = allied_match.group(7)

            headers = ["Quantity", "Item#", "Description", "Pack", "Size", "Unit Price", "Total"]
            for h in headers:
                if h not in detected_headers:
                    detected_headers.append(h)

            hw_note = None
            spec_flag = None
            for kw in ["SHORT", "WRONG", "MISPICK", "BROKEN", "REFUSED"]:
                if kw in line.upper():
                    hw_note = f"Handwritten notation: {kw}"
                    spec_flag = kw
                    break

            line_items.append(
                LineItem(
                    line_number=len(line_items) + 1,
                    quantity=float(qty),
                    item_number=item_code,
                    description=desc,
                    unit_price=float(price),
                    line_total=float(total),
                    raw_columns={
                        "Quantity": qty,
                        "Item#": item_code,
                        "Description": desc,
                        "Pack": pack,
                        "Size": size,
                        "Unit Price": price,
                        "Total": total,
                    },
                    handwritten_note=hw_note,
                    special_flag=spec_flag,
                )
            )
            continue

    return header, line_items, detected_headers
