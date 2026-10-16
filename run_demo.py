import sys
import json
from pathlib import Path
from extractor import process_invoice_extraction
from validator import validate_invoice_data
from excel_generator import generate_invoice_excel
from schemas import ExtractedInvoiceData

def main():
    print("==========================================================")
    print(" INVOICE EXTRACTION & AUTOMATION SYSTEM")
    print("==========================================================")

    # Allow custom file path from command line e.g. python run_demo.py my_invoice.pdf
    if len(sys.argv) > 1:
        sample_file = Path(sys.argv[1])
    else:
        sample_file = Path("sample_invoice.txt")
        if not sample_file.exists():
            sample_file.write_text("Generic Invoice Document Sample\nInvoice#: INV-1001 Date: 2026-09-29\nITEM-101 Beverage Product 10 20.00 200.00\nTOTAL: 200.00")

    if not sample_file.exists():
        print(f"[ERROR] File not found: {sample_file.resolve()}")
        return

    print(f"\n[1/3] Extracting Invoice Data from '{sample_file.name}' via Mistral AI...")
    try:
        header, line_items = process_invoice_extraction(sample_file)
    except Exception as e:
        print(f"\n[ERROR] Extraction failed: {e}")
        return

    print(f"      Extracted Vendor: {header.vendor_name or 'N/A'}")
    print(f"      Invoice Number:   {header.invoice_number or 'N/A'}")
    print(f"      PO Number:        {header.po_number or 'N/A'}")
    print(f"      Extracted Items:  {len(line_items)} line items")

    print("\n[2/3] Executing Mathematical Auditor & Validation Rules...")
    val_header, val_items, val_result = validate_invoice_data(header, line_items)
    print(f"      Validation Passed: {val_result.is_valid}")
    print(f"      Extracted Total:   ${val_result.extracted_invoice_total or 0.0:,.2f}")
    print(f"      Calculated Total:  ${val_result.calculated_line_items_total:,.2f}")

    extracted_data = ExtractedInvoiceData(
        header=val_header,
        line_items=val_items,
        validation=val_result
    )

    print("\n[3/3] Generating Professional Excel Workbook (.xlsx)...")
    output_excel = Path(f"Extracted_{sample_file.stem}.xlsx")
    generate_invoice_excel(extracted_data, output_excel)

    print(f"      Excel File Generated: {output_excel.resolve()}")

    print("\n==========================================================")
    print(" EXTRACTION & VALIDATION SUMMARY JSON")
    print("==========================================================")
    
    summary_json = {
        "header": val_header.model_dump(),
        "line_items_count": len(val_items),
        "first_3_items": [item.model_dump() for item in val_items[:3]],
        "validation": val_result.model_dump()
    }
    print(json.dumps(summary_json, indent=2))
    print("==========================================================")
    print(f"SUCCESS! You can open the generated Excel file at:\n{output_excel.resolve()}")

if __name__ == "__main__":
    main()
