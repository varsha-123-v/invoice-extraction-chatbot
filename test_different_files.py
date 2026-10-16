from pathlib import Path
from extractor import process_invoice_extraction
from validator import validate_invoice_data
from excel_generator import generate_invoice_excel
from schemas import ExtractedInvoiceData

def test_file(file_path: Path):
    print(f"\n----------------------------------------------------------")
    print(f" TESTING FILE: {file_path.name}")
    print(f"----------------------------------------------------------")
    
    extraction_res = process_invoice_extraction(file_path)
    header, line_items = extraction_res.header, extraction_res.line_items
    val_header, val_items, val_result = validate_invoice_data(header, line_items)

    print(f"Detected Table Headers: {extraction_res.detected_table_headers}")
    print(f"Raw Header Fields:      {val_header.raw_header_fields}")
    print(f"Vendor Name:            {val_header.vendor_name}")
    print(f"Invoice Number:         {val_header.invoice_number}")
    print(f"Invoice Date:           {val_header.invoice_date}")
    print(f"PO Number:              {val_header.po_number}")
    print(f"Total Amount:           ${val_header.invoice_total:,.2f}")
    print(f"Line Items Count:       {len(val_items)}")
    print("Sample Line Items (with raw_columns):")
    for idx, item in enumerate(val_items[:3], 1):
        print(f"   {idx}. Code: {item.item_number} | Desc: {item.description} | Qty: {item.quantity} | Total: ${item.line_total:.2f}")
        print(f"      Raw Columns: {item.raw_columns}")

    # Test Excel generation
    ext_data = ExtractedInvoiceData(
        header=val_header,
        line_items=val_items,
        validation=val_result,
        detected_table_headers=extraction_res.detected_table_headers,
    )
    excel_path = Path(f"Extracted_{file_path.stem}.xlsx")
    generate_invoice_excel(ext_data, excel_path)
    print(f"Successfully generated dynamic Excel: {excel_path} (exists={excel_path.exists()})")

def main():
    # File 1: Shore Point Sample
    shore_file = Path("Shore_Point_770921.pdf")
    shore_file.write_text("SHORE POINT DISTRIBUTING CO INC\nInvoice#: 770921 Date: Sep 28 2026 PO# 6-29904\n04427 ARN 1/2 7 30.00 210.00")

    # File 2: Icarus Brewing / Different Vendor Sample
    icarus_file = Path("Icarus_Brewing_Invoice_9941.txt")
    icarus_file.write_text(
        "ICARUS BREWING LLC\n"
        "1650 OAK STREET, LAKEWOOD, NJ 08701\n"
        "INVOICE #: INV-9941\n"
        "PO #: PO-88321\n"
        "DATE: 2026-09-25\n"
        "CUSTOMER: WINE OUTLET WALL\n\n"
        "ITEM-101 YACHT JUICE IPA 12 45.00 540.00\n"
        "ITEM-202 KALASHNIKOV STOUT 5 55.00 275.00\n"
        "ITEM-303 ALIEN CHURCH IPA 8 48.00 384.00\n\n"
        "TOTAL AMOUNT: 1199.00"
    )

    test_file(shore_file)
    test_file(icarus_file)

if __name__ == "__main__":
    main()
