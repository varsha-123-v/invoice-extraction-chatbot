from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from schemas import ExtractedInvoiceData


def generate_invoice_excel(extracted_data: ExtractedInvoiceData, output_path: Path) -> str:
    """
    Generates a professionally formatted Excel (.xlsx) file using openpyxl with 2 sheets:
    - Sheet 1: Invoice Details & Audit Validation Summary
    - Sheet 2: Line Items
    """
    wb = openpyxl.Workbook()
    
    # ---------------------------------------------------------
    # Styles Definition
    # ---------------------------------------------------------
    HEADER_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid") # Dark Navy Slate
    SECTION_FILL = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid") # Deep Navy
    SUBHEADER_FILL = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid") # Light Slate
    TOTAL_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    VALID_PASS_FILL = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid") # Soft Green
    VALID_FAIL_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid") # Soft Red

    FONT_TITLE = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    FONT_HEADER = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    FONT_SUBHEADER = Font(name="Calibri", size=11, bold=True, color="334155")
    FONT_BOLD = Font(name="Calibri", size=11, bold=True)
    FONT_REGULAR = Font(name="Calibri", size=11)
    FONT_VALID_PASS = Font(name="Calibri", size=11, bold=True, color="166534")
    FONT_VALID_FAIL = Font(name="Calibri", size=11, bold=True, color="991B1B")

    THIN_BORDER_SIDE = Side(border_style="thin", color="CBD5E1")
    BORDER_ALL = Border(left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE, bottom=THIN_BORDER_SIDE)
    BORDER_DOUBLE_BOTTOM = Border(top=THIN_BORDER_SIDE, bottom=Side(border_style="double", color="0F172A"))

    ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
    ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")
    ALIGN_CENTER = Alignment(horizontal="center", vertical="center")

    header = extracted_data.header
    items = extracted_data.line_items
    val = extracted_data.validation

    # =========================================================
    # SHEET 1: Invoice Details
    # =========================================================
    ws1 = wb.active
    ws1.title = "Invoice Details"
    ws1.views.sheetView[0].showGridLines = True

    # Title Banner
    ws1.merge_cells("A1:D1")
    ws1["A1"] = "INVOICE AUTOMATION & AUDIT REPORT"
    ws1["A1"].font = FONT_TITLE
    ws1["A1"].fill = SECTION_FILL
    ws1["A1"].alignment = ALIGN_CENTER
    ws1.row_dimensions[1].height = 35

    # Section 1: Header Information
    ws1.merge_cells("A3:D3")
    ws1["A3"] = "1. INVOICE HEADER INFORMATION"
    ws1["A3"].font = FONT_HEADER
    ws1["A3"].fill = HEADER_FILL
    ws1["A3"].alignment = ALIGN_LEFT
    ws1.row_dimensions[3].height = 24

    header_metadata = [
        ("Vendor Name", header.vendor_name or "N/A", "Invoice Number", header.invoice_number or "N/A"),
        ("Invoice Date", header.invoice_date or "N/A", "PO Number", header.po_number or "N/A"),
        ("Store / Customer", header.store_customer or "N/A", "Terms", header.terms or "N/A"),
        ("Due Date", header.due_date or "N/A", "Driver / Delivery", header.driver_info or "N/A"),
        ("Payment Info", header.payment_info or "N/A", "Handwritten Notes", header.handwritten_notes or "None"),
    ]

    row = 4
    for label1, val1, label2, val2 in header_metadata:
        ws1.cell(row=row, column=1, value=label1).font = FONT_SUBHEADER
        ws1.cell(row=row, column=1).fill = SUBHEADER_FILL
        ws1.cell(row=row, column=1).border = BORDER_ALL
        
        ws1.cell(row=row, column=2, value=val1).font = FONT_REGULAR
        ws1.cell(row=row, column=2).border = BORDER_ALL

        ws1.cell(row=row, column=3, value=label2).font = FONT_SUBHEADER
        ws1.cell(row=row, column=3).fill = SUBHEADER_FILL
        ws1.cell(row=row, column=3).border = BORDER_ALL

        ws1.cell(row=row, column=4, value=val2).font = FONT_REGULAR
        ws1.cell(row=row, column=4).border = BORDER_ALL
        ws1.row_dimensions[row].height = 20
        row += 1

    # Section 2: Financial Summary
    row += 1
    ws1.merge_cells(f"A{row}:D{row}")
    ws1[f"A{row}"] = "2. FINANCIAL SUMMARY & CROSS-CHECK"
    ws1[f"A{row}"].font = FONT_HEADER
    ws1[f"A{row}"].fill = HEADER_FILL
    ws1[f"A{row}"].alignment = ALIGN_LEFT
    ws1.row_dimensions[row].height = 24
    row += 1

    financials = [
        ("Subtotal", header.subtotal, "Total Discounts", header.discounts),
        ("Taxes", header.tax, "Total Bottle Deposits", header.deposits),
        ("Original Extracted PDF Total", header.invoice_total, "Line Items Calculated Sum", val.calculated_line_items_total),
        ("Shortage / Mispick Deductions", header.total_deductions, "Deducted Items Count", val.deducted_items_count),
        ("FINAL ADJUSTED INVOICE TOTAL", header.adjusted_final_total, "Validation Status", "PASSED" if val.is_valid else "NEEDS REVIEW"),
    ]

    for label1, val1, label2, val2 in financials:
        ws1.cell(row=row, column=1, value=label1).font = FONT_SUBHEADER
        ws1.cell(row=row, column=1).fill = SUBHEADER_FILL
        ws1.cell(row=row, column=1).border = BORDER_ALL

        # Format number or string
        c2 = ws1.cell(row=row, column=2, value=val1 if val1 is not None else "N/A")
        if label1 == "FINAL ADJUSTED INVOICE TOTAL":
            c2.font = FONT_VALID_PASS
            c2.fill = VALID_PASS_FILL
        else:
            c2.font = FONT_BOLD if "TOTAL" in label1.upper() or "TOTALS" in label1.upper() else FONT_REGULAR

        if isinstance(val1, (int, float)):
            c2.number_format = "$#,##0.00"
        c2.border = BORDER_ALL

        ws1.cell(row=row, column=3, value=label2).font = FONT_SUBHEADER
        ws1.cell(row=row, column=3).fill = SUBHEADER_FILL
        ws1.cell(row=row, column=3).border = BORDER_ALL

        c4 = ws1.cell(row=row, column=4, value=val2 if val2 is not None else "N/A")
        if isinstance(val2, (int, float)):
            c4.number_format = "$#,##0.00" if isinstance(val2, float) else "#,##0"
            c4.font = FONT_BOLD
        elif label2 == "Validation Status":
            c4.font = FONT_VALID_PASS if val.is_valid else FONT_VALID_FAIL
            c4.fill = VALID_PASS_FILL if val.is_valid else VALID_FAIL_FILL
        else:
            c4.font = FONT_REGULAR
        c4.border = BORDER_ALL
        ws1.row_dimensions[row].height = 20
        row += 1

    # Section 3: All Detected Document Fields (Dynamic PDF Extraction)
    if header.raw_header_fields:
        row += 1
        ws1.merge_cells(f"A{row}:D{row}")
        ws1[f"A{row}"] = "3. ALL DETECTED DOCUMENT FIELDS (DYNAMIC PDF EXTRACTION)"
        ws1[f"A{row}"].font = FONT_HEADER
        ws1[f"A{row}"].fill = HEADER_FILL
        ws1[f"A{row}"].alignment = ALIGN_LEFT
        ws1.row_dimensions[row].height = 24
        row += 1

        rf_items = list(header.raw_header_fields.items())
        for i in range(0, len(rf_items), 2):
            k1, v1 = rf_items[i]
            k2, v2 = rf_items[i+1] if i+1 < len(rf_items) else ("", "")

            ws1.cell(row=row, column=1, value=str(k1)).font = FONT_SUBHEADER
            ws1.cell(row=row, column=1).fill = SUBHEADER_FILL
            ws1.cell(row=row, column=1).border = BORDER_ALL

            ws1.cell(row=row, column=2, value=str(v1)).font = FONT_REGULAR
            ws1.cell(row=row, column=2).border = BORDER_ALL

            ws1.cell(row=row, column=3, value=str(k2)).font = FONT_SUBHEADER
            ws1.cell(row=row, column=3).fill = SUBHEADER_FILL
            ws1.cell(row=row, column=3).border = BORDER_ALL

            ws1.cell(row=row, column=4, value=str(v2)).font = FONT_REGULAR
            ws1.cell(row=row, column=4).border = BORDER_ALL
            ws1.row_dimensions[row].height = 20
            row += 1

    # Section 4: Missing Fields & Audit Summary Notes
    row += 1
    ws1.merge_cells(f"A{row}:D{row}")
    ws1[f"A{row}"] = "4. AUDIT SUMMARY & SHORTAGE DEDUCTION NOTES"
    ws1[f"A{row}"].font = FONT_HEADER
    ws1[f"A{row}"].fill = HEADER_FILL
    ws1[f"A{row}"].alignment = ALIGN_LEFT
    ws1.row_dimensions[row].height = 24
    row += 1

    ws1.cell(row=row, column=1, value="Missing Fields").font = FONT_SUBHEADER
    ws1.cell(row=row, column=1).fill = SUBHEADER_FILL
    ws1.cell(row=row, column=1).border = BORDER_ALL
    ws1.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws1.cell(row=row, column=2, value=", ".join(val.missing_fields) if val.missing_fields else "None").font = FONT_REGULAR
    row += 1

    ws1.cell(row=row, column=1, value="Audit & Deduction Notes").font = FONT_SUBHEADER
    ws1.cell(row=row, column=1).fill = SUBHEADER_FILL
    ws1.cell(row=row, column=1).border = BORDER_ALL
    ws1.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws1.cell(row=row, column=2, value="\n".join(val.summary_notes) if val.summary_notes else "None").font = FONT_REGULAR
    ws1.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="center")

    # Auto-adjust column widths for Sheet 1
    ws1.column_dimensions["A"].width = 28
    ws1.column_dimensions["B"].width = 38
    ws1.column_dimensions["C"].width = 28
    ws1.column_dimensions["D"].width = 38

    # =========================================================
    # SHEET 2: Line Items (Standardized)
    # =========================================================
    ws2 = wb.create_sheet(title="Line Items")
    ws2.views.sheetView[0].showGridLines = True

    # Identify any extra raw columns not represented in standard columns
    standard_labels = {"line #", "item code", "upc / barcode", "description", "qty", "unit price", "discount", "deposit", "net price", "line total", "special flag / status", "confidence"}
    extra_raw_keys = []
    for item in items:
        if item.raw_columns:
            for k in item.raw_columns.keys():
                if k.lower() not in standard_labels and k not in extra_raw_keys:
                    extra_raw_keys.append(k)

    columns = [
        ("Line #", 8, ALIGN_CENTER),
        ("Item Code", 14, ALIGN_CENTER),
        ("UPC / Barcode", 18, ALIGN_CENTER),
        ("Description", 38, ALIGN_LEFT),
        ("Qty", 10, ALIGN_RIGHT),
        ("Unit Price", 14, ALIGN_RIGHT),
        ("Discount", 12, ALIGN_RIGHT),
        ("Deposit", 12, ALIGN_RIGHT),
        ("Net Price", 14, ALIGN_RIGHT),
        ("Line Total", 16, ALIGN_RIGHT),
        ("Special Flag / Status", 22, ALIGN_CENTER),
        ("Confidence", 12, ALIGN_CENTER),
    ]

    for extra_k in extra_raw_keys:
        columns.append((f"[Raw] {extra_k}", max(len(extra_k) + 8, 16), ALIGN_LEFT))

    # Header Row
    ws2.row_dimensions[1].height = 26
    for col_idx, (col_name, col_width, align) in enumerate(columns, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=col_name)
        cell.font = FONT_HEADER
        cell.fill = HEADER_FILL
        cell.alignment = align
        cell.border = BORDER_ALL
        ws2.column_dimensions[get_column_letter(col_idx)].width = col_width

    # Data Rows
    current_row = 2
    for item in items:
        ws2.row_dimensions[current_row].height = 20

        vals = [
            (item.line_number, ALIGN_CENTER, None),
            (item.item_number or "-", ALIGN_CENTER, None),
            (item.upc or "-", ALIGN_CENTER, None),
            (item.description, ALIGN_LEFT, None),
            (item.quantity, ALIGN_RIGHT, "#,##0"),
            (item.unit_price, ALIGN_RIGHT, "$#,##0.00"),
            (item.discount, ALIGN_RIGHT, "$#,##0.00"),
            (item.deposit, ALIGN_RIGHT, "$#,##0.00"),
            (item.net_price, ALIGN_RIGHT, "$#,##0.00"),
            (item.line_total, ALIGN_RIGHT, "$#,##0.00"),
            (item.special_flag or "OK", ALIGN_CENTER, None),
            (f"{int(item.confidence * 100)}%", ALIGN_CENTER, None),
        ]

        # Extra raw columns
        for extra_k in extra_raw_keys:
            raw_v = item.raw_columns.get(extra_k, "-") if item.raw_columns else "-"
            vals.append((raw_v, ALIGN_LEFT, None))

        # Check if item is deducted due to mispick/broken/refused/shortage
        is_deducted = False
        if item.special_flag and any(kw in item.special_flag.upper() for kw in ["MISPICK", "BROKEN", "REFUSED", "SHORT", "WRONG"]):
            is_deducted = True

        for col_idx, (val_entry, align, num_fmt) in enumerate(vals, start=1):
            cell = ws2.cell(row=current_row, column=col_idx, value=val_entry)
            cell.font = FONT_REGULAR
            cell.alignment = align
            cell.border = BORDER_ALL
            if is_deducted:
                cell.fill = VALID_FAIL_FILL
                cell.font = Font(name="Calibri", size=11, color="991B1B")
            if num_fmt:
                cell.number_format = num_fmt

        current_row += 1

    # Summary Rows
    ws2.row_dimensions[current_row].height = 22
    ws2.cell(row=current_row, column=4, value="ORIGINAL PDF LINE ITEMS TOTAL").font = FONT_BOLD
    ws2.cell(row=current_row, column=4).alignment = ALIGN_RIGHT
    ws2.cell(row=current_row, column=10, value=f"=SUM(J2:J{current_row-1})").font = FONT_BOLD
    ws2.cell(row=current_row, column=10).number_format = "$#,##0.00"
    ws2.cell(row=current_row, column=10).alignment = ALIGN_RIGHT
    ws2.cell(row=current_row, column=10).border = BORDER_ALL
    current_row += 1

    ws2.row_dimensions[current_row].height = 24
    ws2.cell(row=current_row, column=4, value="FINAL ADJUSTED INVOICE TOTAL").font = FONT_VALID_PASS
    ws2.cell(row=current_row, column=4).alignment = ALIGN_RIGHT

    tot_cell = ws2.cell(row=current_row, column=10, value=header.adjusted_final_total or header.invoice_total or 0.0)
    tot_cell.font = FONT_VALID_PASS
    tot_cell.number_format = "$#,##0.00"
    tot_cell.alignment = ALIGN_RIGHT
    tot_cell.fill = VALID_PASS_FILL
    tot_cell.border = BORDER_DOUBLE_BOTTOM

    # =========================================================
    # SHEET 3: Original PDF Table (Dynamic Extraction)
    # =========================================================
    raw_table_headers = list(extracted_data.detected_table_headers)
    for item in items:
        if item.raw_columns:
            for k in item.raw_columns.keys():
                if k not in raw_table_headers:
                    raw_table_headers.append(k)

    if raw_table_headers:
        ws_raw = wb.create_sheet(title="Original PDF Table")
        ws_raw.views.sheetView[0].showGridLines = True

        # Title Banner
        end_col_letter = get_column_letter(max(len(raw_table_headers), 1))
        ws_raw.merge_cells(f"A1:{end_col_letter}1")
        ws_raw["A1"] = "ORIGINAL EXTRACTED PDF TABLE (VERBATIM HEADINGS & VALUES)"
        ws_raw["A1"].font = FONT_TITLE
        ws_raw["A1"].fill = SECTION_FILL
        ws_raw["A1"].alignment = ALIGN_CENTER
        ws_raw.row_dimensions[1].height = 32

        # Header Row
        ws_raw.row_dimensions[3].height = 24
        for c_idx, h_name in enumerate(raw_table_headers, start=1):
            cell = ws_raw.cell(row=3, column=c_idx, value=h_name)
            cell.font = FONT_HEADER
            cell.fill = HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = BORDER_ALL
            ws_raw.column_dimensions[get_column_letter(c_idx)].width = max(len(str(h_name)) + 4, 16)

        # Data Rows
        r_idx = 4
        for item in items:
            ws_raw.row_dimensions[r_idx].height = 20
            for c_idx, h_name in enumerate(raw_table_headers, start=1):
                raw_val = item.raw_columns.get(h_name, "-") if item.raw_columns else "-"
                cell = ws_raw.cell(row=r_idx, column=c_idx, value=raw_val)
                cell.font = FONT_REGULAR
                cell.alignment = ALIGN_LEFT
                cell.border = BORDER_ALL
            r_idx += 1
    wb.save(output_path)
    return str(output_path)
