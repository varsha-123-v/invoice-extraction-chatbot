from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    model_config = {"extra": "allow"}

    line_number: int = Field(..., description="Line index 1-N")
    item_number: Optional[str] = Field(None, description="Vendor catalog / item number")
    upc: Optional[str] = Field(None, description="Scanned barcode / GTIN / UPC")
    description: str = Field("Item", description="Full item description")
    quantity: float = Field(0.0, description="Quantity billed")
    unit_price: float = Field(0.0, description="Gross unit price before discount/deposit")
    discount: float = Field(0.0, description="Unit discount amount")
    deposit: float = Field(0.0, description="Unit bottle deposit fee")
    net_price: float = Field(0.0, description="Net unit price after discount + deposit")
    line_total: float = Field(0.0, description="Line total amount")
    special_flag: Optional[str] = Field(None, description="Special status: OUT_OF_STOCK, SHORTAGE, BROKEN, REFUSED, CHECKMARK, etc.")
    confidence: float = Field(1.0, description="Extraction confidence score (0.0 to 1.0)")
    raw_columns: Dict[str, Any] = Field(default_factory=dict, description="Original column headings and values exactly as printed on this PDF table row")
    handwritten_quantity: Optional[float] = Field(None, description="Inline handwritten adjusted quantity if present")
    handwritten_unit_price: Optional[float] = Field(None, description="Inline handwritten adjusted price if present")
    handwritten_note: Optional[str] = Field(None, description="Inline handwritten note or mark for this item")


class InvoiceHeader(BaseModel):
    model_config = {"extra": "allow"}

    vendor_name: Optional[str] = Field(None, description="Full vendor / distributor name")
    vendor_address: Optional[str] = Field(None, description="Vendor address")
    vendor_phone: Optional[str] = Field(None, description="Vendor contact phone")
    invoice_number: Optional[str] = Field(None, description="Unique invoice number")
    invoice_date: Optional[str] = Field(None, description="Invoice date (YYYY-MM-DD or raw string)")
    po_number: Optional[str] = Field(None, description="Purchase Order number (printed or handwritten)")
    handwritten_po_number: Optional[str] = Field(None, description="Handwritten PO number if distinct from printed PO")
    store_customer: Optional[str] = Field(None, description="Customer / Store ship-to name")
    store_address: Optional[str] = Field(None, description="Store shipping address")
    due_date: Optional[str] = Field(None, description="Payment due date")
    terms: Optional[str] = Field(None, description="Payment terms e.g. CHARGE, Net 30")
    subtotal: Optional[float] = Field(None, description="Header subtotal before taxes/discounts")
    tax: Optional[float] = Field(0.0, description="Tax amount")
    deposits: Optional[float] = Field(0.0, description="Total deposit fee")
    discounts: Optional[float] = Field(0.0, description="Total invoice discount")
    invoice_total: Optional[float] = Field(None, description="Full invoice total extracted from PDF")
    adjusted_final_total: Optional[float] = Field(None, description="Final total after deducting mispicks/broken/refused/short items")
    total_deductions: float = Field(0.0, description="Sum of deducted item line totals")
    payment_info: Optional[str] = Field(None, description="Payment details / A/R breakdown")
    handwritten_notes: Optional[str] = Field(None, description="Any handwritten text detected on margin/header")
    driver_info: Optional[str] = Field(None, description="Driver ID and signature info")
    raw_header_fields: Dict[str, Any] = Field(default_factory=dict, description="All original printed and handwritten header labels and values")

    def __getattr__(self, name: str) -> Any:
        if name in self.__dict__:
            return self.__dict__[name]
        extra = self.__dict__.get("__pydantic_extra__")
        if extra and name in extra:
            return extra[name]
        raw = self.__dict__.get("raw_header_fields") or {}
        if name in raw:
            return raw[name]
        name_norm = name.replace("_", " ").lower()
        for k, v in raw.items():
            if k.lower() == name.lower() or k.lower() == name_norm:
                return v
        return None


class ValidationResult(BaseModel):
    is_valid: bool = Field(..., description="True if no critical math or data errors found")
    extracted_invoice_total: Optional[float] = Field(None, description="Header total extracted from invoice")
    calculated_line_items_total: float = Field(0.0, description="Sum of all calculated line item totals")
    total_difference: float = Field(0.0, description="Abs difference between extracted & calculated total")
    adjusted_final_total: Optional[float] = Field(None, description="Final invoice total after deducting mispick/broken/refused/short items")
    total_deductions: float = Field(0.0, description="Total deduction amount for mispick/broken/refused/short items")
    deducted_items_count: int = Field(0, description="Count of line items marked as short/mispick/broken/refused")
    missing_fields: List[str] = Field(default_factory=list, description="Fields that were null or absent")
    uncertain_fields: List[str] = Field(default_factory=list, description="Fields with low confidence or flags")
    math_discrepancies: List[str] = Field(default_factory=list, description="Specific line math errors")
    summary_notes: List[str] = Field(default_factory=list, description="Human-readable audit notes")


class ExtractedInvoiceData(BaseModel):
    detected_table_headers: List[str] = Field(default_factory=list, description="Original column header names detected in the document table")
    header: InvoiceHeader
    line_items: List[LineItem]
    validation: ValidationResult


class ExtractionResponse(BaseModel):
    file_id: str
    filename: str
    download_excel_url: str
    extracted_data: ExtractedInvoiceData
    provider_used: Optional[str] = Field("Mistral AI", description="AI provider used for this extraction")
    status: Optional[str] = Field("success", description="Overall extraction processing status")



# Backward compatibility aliases
PrintedHeader = InvoiceHeader
PrintedLineItem = LineItem
PrintedExtraction = ExtractedInvoiceData
