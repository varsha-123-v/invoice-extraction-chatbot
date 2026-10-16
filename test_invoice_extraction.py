from pathlib import Path
from fastapi.testclient import TestClient

from main import app
from extractor import process_invoice_extraction
from validator import validate_invoice_data

client = TestClient(app)

def test_scanned_pdf_extraction():
    """Test 1: Scanned PDF invoice extracted via Mistral Vision model."""
    scanned_pdf = Path("temp/uploads/001a341e_Epson_09282026100345.pdf")
    assert scanned_pdf.exists(), f"Sample PDF {scanned_pdf} not found"

    header, line_items = process_invoice_extraction(scanned_pdf)
    assert len(line_items) > 0, "Expected at least 1 line item extracted from scanned PDF"
    assert header.vendor_name is not None, "Expected vendor name to be extracted"
    
    val_header, val_items, val_res = validate_invoice_data(header, line_items)
    assert len(val_items) == len(line_items)
    print(f"\n[Scanned PDF Success] Vendor: {val_header.vendor_name}, Items: {len(val_items)}, Total: ${val_header.invoice_total}")

def test_digital_text_invoice_extraction():
    """Test 2: Digital text invoice extraction (sample_invoice.txt and Shore Point)."""
    sample_txt = Path("sample_invoice.txt")
    if sample_txt.exists():
        header, line_items = process_invoice_extraction(sample_txt)
        assert len(line_items) > 0, "Expected line items from digital invoice text"
        print(f"\n[Digital Text Success] Vendor: {header.vendor_name}, Items: {len(line_items)}")

    # Shore Point file
    shore_pdf = Path("Shore_Point_770921.pdf")
    if shore_pdf.exists():
        header, line_items = process_invoice_extraction(shore_pdf)
        assert len(line_items) > 0, "Expected line items from Shore Point invoice"
        print(f"\n[Shore Point Success] Vendor: {header.vendor_name}, Items: {len(line_items)}")

def test_unparseable_document_raises_error():
    """Test 3: Unparseable document must raise RuntimeError instead of empty items."""
    invalid_file = Path("temp/test_invalid_doc.txt")
    invalid_file.parent.mkdir(parents=True, exist_ok=True)
    invalid_file.write_text("Random non-invoice content with no products or amounts.")
    
    raised = False
    try:
        process_invoice_extraction(invalid_file)
    except RuntimeError as e:
        raised = True
        assert "Invoice extraction failed" in str(e)
        print(f"\n[Failure Handling Success] Correctly raised RuntimeError: {e}")
    finally:
        if invalid_file.exists():
            invalid_file.unlink()
    assert raised, "Expected RuntimeError was not raised!"

def test_api_endpoint_success_and_failure():
    """Test 4: FastAPI /extract-invoice returns 200 on valid invoice, 422/500 on invalid."""
    # 4a: Endpoint with invalid file returns non-200 HTTP error
    invalid_content = b"Unparseable file content without any invoice items."
    resp_fail = client.post(
        "/extract-invoice",
        files={"file": ("invalid_invoice.txt", invalid_content, "text/plain")}
    )
    assert resp_fail.status_code == 422, f"Expected 422 Unprocessable Entity, got {resp_fail.status_code}"
    assert "extraction failed" in resp_fail.json().get("detail", "").lower()
    print(f"\n[API Error Handling Success] Status: {resp_fail.status_code}, Detail: {resp_fail.json().get('detail')}")

    # 4b: Endpoint with valid file returns 200
    sample_txt = Path("sample_invoice.txt")
    if sample_txt.exists():
        with open(sample_txt, "rb") as f:
            resp_success = client.post(
                "/extract-invoice",
                files={"file": (sample_txt.name, f.read(), "text/plain")}
            )
        assert resp_success.status_code == 200, f"Expected 200 OK, got {resp_success.status_code}"
        data = resp_success.json()
        assert len(data["extracted_data"]["line_items"]) > 0
        assert data["download_excel_url"] is not None
        print(f"\n[API Success] Status: 200 OK, Download: {data['download_excel_url']}, Items: {len(data['extracted_data']['line_items'])}")

def test_epson_invoice_extraction():
    """Test 5: Extraction using Epson_10062026081913.pdf."""
    epson_pdf = Path("Epson_10062026081913.pdf")
    if not epson_pdf.exists():
        epson_pdf = Path("temp/uploads/384a74ff_Epson_10062026081913.pdf")
    assert epson_pdf.exists(), f"Epson PDF {epson_pdf} not found"

    header, line_items = process_invoice_extraction(epson_pdf)
    assert len(line_items) > 0, "Expected line items from Epson_10062026081913.pdf"

    val_header, val_items, val_res = validate_invoice_data(header, line_items)
    assert val_res.is_valid, "Expected validation to succeed"

    from excel_generator import generate_invoice_excel
    from schemas import ExtractedInvoiceData
    ext_data = ExtractedInvoiceData(
        header=val_header,
        line_items=val_items,
        validation=val_res
    )
    out_excel = Path("temp/exports/Extracted_Epson_10062026081913.xlsx")
    generate_invoice_excel(ext_data, out_excel)
    assert out_excel.exists() and out_excel.stat().st_size > 0
    print(f"\n[Epson PDF Success] Vendor: {val_header.vendor_name}, Store: {val_header.store_customer}, Items: {len(val_items)}, Excel: {out_excel}")

if __name__ == "__main__":
    test_digital_text_invoice_extraction()
    test_unparseable_document_raises_error()
    test_api_endpoint_success_and_failure()
    test_epson_invoice_extraction()
    print("\nALL INVOICE EXTRACTION TESTS COMPLETED SUCCESSFULLY!")
