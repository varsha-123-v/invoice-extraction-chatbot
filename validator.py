import math
import re
from typing import List, Tuple
from schemas import InvoiceHeader, LineItem, ValidationResult


DEDUCTION_KEYWORDS = {
    "MISPICK", "MIS-PICK", "MIS PICK",
    "BROKEN", "DAMAGED",
    "REFUSED", "RETURNED", "REJECT", "REJECTED",
    "WRONG_ITEM", "WRONG ITEM", "WRONG",
    "SHORTAGE", "SHORT", "OUT_OF_STOCK", "OUT OF STOCK"
}


def is_deducted_item(item: LineItem) -> bool:
    """Checks if line item has a special flag or description indicating it was mispicked, broken, shorted, or refused."""
    if item.special_flag:
        flag_upper = item.special_flag.upper()
        if any(kw in flag_upper for kw in DEDUCTION_KEYWORDS):
            return True
    if item.description:
        desc_upper = item.description.upper()
        if any(kw in desc_upper for kw in DEDUCTION_KEYWORDS):
            return True
    return False


def validate_invoice_data(header: InvoiceHeader, line_items: List[LineItem]) -> Tuple[InvoiceHeader, List[LineItem], ValidationResult]:
    """
    Validates extracted invoice data without forcing artificial net price formulas.
    Preserves exact PDF line totals and calculates the final adjusted invoice total
    by deducting items marked as mispick, broken, refused, wrong item, or short.
    """
    missing_fields: List[str] = []
    uncertain_fields: List[str] = []
    math_discrepancies: List[str] = []
    summary_notes: List[str] = []

    # 1. Inspect Header Missing Fields
    if not header.vendor_name:
        missing_fields.append("vendor_name")
    if not header.invoice_number:
        missing_fields.append("invoice_number")
    if not header.invoice_date:
        missing_fields.append("invoice_date")
    if not header.po_number:
        missing_fields.append("po_number")
    if header.invoice_total is None:
        missing_fields.append("invoice_total")
    if not header.store_customer:
        missing_fields.append("store_customer")

    # Flag handwritten notes if present
    if header.handwritten_notes:
        summary_notes.append(f"Handwritten notes detected: {header.handwritten_notes}")

    # 2. Process Line Items Exact Values & Deductions
    calculated_line_sum = 0.0
    total_deductions = 0.0
    deducted_items_count = 0

    for item in line_items:
        qty = item.quantity or 0.0
        uprice = item.unit_price or 0.0
        
        # Check if qty or uprice can be safely resolved from raw_columns if missing
        if (qty == 0.0 or uprice == 0.0) and item.raw_columns:
            for k, v in item.raw_columns.items():
                k_up = k.upper()
                if qty == 0.0 and any(qk in k_up for qk in ["QTY", "QUANTITY", "CAS", "CS", "BILLED", "DELIVERED"]):
                    try:
                        parsed_q = float(re.sub(r'[^\d.-]', '', str(v)))
                        if parsed_q > 0:
                            qty = parsed_q
                            item.quantity = qty
                    except Exception:
                        pass
                if uprice == 0.0 and any(pk in k_up for pk in ["PRICE", "COST", "RATE", "NET"]):
                    try:
                        parsed_p = float(re.sub(r'[^\d.-]', '', str(v)))
                        if parsed_p > 0:
                            uprice = parsed_p
                            item.unit_price = uprice
                    except Exception:
                        pass

        # Ensure net_price exists
        if item.net_price is None or item.net_price == 0.0:
            item.net_price = uprice

        # If OUT OF STOCK, line_total must be 0.0
        if item.special_flag and "OUT_OF_STOCK" in item.special_flag.upper():
            item.quantity = 0.0
            item.line_total = 0.0

        # Preserve exact line total as extracted from PDF; only compute if missing or 0.0
        if (item.line_total is None or item.line_total == 0.0) and qty > 0 and uprice > 0:
            item.line_total = round(qty * (item.net_price or uprice), 2)

        line_tot = item.line_total or 0.0
        calculated_line_sum += line_tot

        # Check for handwritten shortage / mispick / broken / refused deduction flags
        if is_deducted_item(item) and line_tot > 0:
            deducted_items_count += 1
            total_deductions += line_tot
            reason = item.special_flag or "Handwritten shortage / deduction"
            summary_notes.append(
                f"Line {item.line_number} ({item.description}): Marked as [{reason}] -> Deducted ${line_tot:.2f} from final invoice total."
            )

    calculated_line_sum = round(calculated_line_sum, 2)
    total_deductions = round(total_deductions, 2)

    # 3. Calculate Original PDF Total and Final Adjusted Total
    extracted_total = header.invoice_total if header.invoice_total is not None else calculated_line_sum
    header.invoice_total = extracted_total

    adjusted_final_total = round(max(0.0, extracted_total - total_deductions), 2)
    header.adjusted_final_total = adjusted_final_total
    header.total_deductions = total_deductions

    summary_notes.append(f"Original Invoice Total (from PDF): ${extracted_total:,.2f}")
    if total_deductions > 0:
        summary_notes.append(
            f"Total Deductions ({deducted_items_count} item(s) mispick/broken/refused/short): -${total_deductions:,.2f}"
        )
        summary_notes.append(f"FINAL ADJUSTED INVOICE TOTAL: ${adjusted_final_total:,.2f}")

    total_diff = round(abs(extracted_total - calculated_line_sum), 2)

    # 4. Overall Validity Determination
    has_identifier = bool(header.invoice_number or header.po_number or header.vendor_name)
    has_total = (extracted_total is not None and extracted_total > 0) or (calculated_line_sum > 0)
    is_valid = has_identifier and has_total

    validation_result = ValidationResult(
        is_valid=is_valid,
        extracted_invoice_total=extracted_total,
        calculated_line_items_total=calculated_line_sum,
        total_difference=total_diff,
        adjusted_final_total=adjusted_final_total,
        total_deductions=total_deductions,
        deducted_items_count=deducted_items_count,
        missing_fields=missing_fields,
        uncertain_fields=uncertain_fields,
        math_discrepancies=math_discrepancies,
        summary_notes=summary_notes,
    )

    return header, line_items, validation_result
