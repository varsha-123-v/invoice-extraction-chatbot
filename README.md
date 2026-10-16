# Invoice Extraction & Handwritten Review Backend

A production-ready FastAPI backend for extracting structured printed invoice details and handwritten annotations separately using **Mistral AI (`pixtral-12b-2409` & `mistral-large-latest`)**, validating line item math, and generating styled 3-sheet **Excel (.xlsx)** reports.

---

## Key Features & Model Recommendations

- **Primary Vision & Processing Model:** **Mistral AI (`pixtral-12b-2409` & `mistral-large-latest`)** for printed & handwritten PDF extraction.
- **2-Pass Extraction Workflow:**
  - **Pass 1 (Printed PO/Invoice Extraction):** Extracts complete printed document content, preserving every number, price, quantity, discount, and total EXACTLY as shown in the original document without auto-correcting or modifying values.
  - **Pass 2 (Handwritten Notes & Marginalia Detection):** Detects handwritten PO annotations, pen checkmarks, handwritten quantity adjustments, price reductions, refunds, corrections, stamps, and signatures separately. Never overwrites printed values; flags unclear handwriting for manual review.
- **3-Sheet Excel Workbook Output (`excel_generator.py`):**
  - **Sheet 1 (`Invoice Details`):** Header metadata, financial summary, and audit cross-checks.
  - **Sheet 2 (`Line Items`):** Itemized line table with unit pricing, net amounts, line totals, and status flags.
  - **Sheet 3 (`Handwritten Review`):** Dedicated audit sheet displaying all detected handwritten entries, flag types, confidence scores, review status, and auditor notes.
- **FastAPI Endpoints:**
  - `POST /extract-invoice`: Upload PDF/Image $\rightarrow$ 2-Pass Extraction $\rightarrow$ Math Validation $\rightarrow$ Generate 3-Sheet Excel $\rightarrow$ Return JSON with download link.
  - `GET /download-excel/{file_id}`: Download formatted 3-Sheet Excel report.
  - `GET /health`: Health check and model readiness status.

---

## Directory Structure

```
c:\Purchase inventory\
├── config.py             # Mistral AI configuration
├── schemas.py            # Pydantic models for Printed, Handwritten, & Validation
├── extractor.py          # AI Vision pipeline & Mistral AI model caller
├── validator.py          # Line math validator & invoice total auditor
├── excel_generator.py    # 3-Sheet Excel workbook generator (openpyxl)
├── main.py               # FastAPI server application & endpoints
├── requirements.txt      # Python dependencies
├── .env.example          # Template for environment variables
├── .env                  # Local environment config
└── README.md             # System documentation
```

---

## Setup & Installation

### 1. Prerequisites
- Python 3.10+ installed on your system.

### 2. Install Dependencies
```bash
# On Windows PowerShell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and configure your API keys:

```env
# Mistral AI API Configuration
MISTRAL_API_KEY=your_mistral_api_key_here
MISTRAL_VISION_MODEL=pixtral-12b-2409
MISTRAL_CHAT_MODEL=mistral-large-latest
```

---

## Running the Server

Start the FastAPI server using `uvicorn`:

```bash
.\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Once started:
- **Interactive Swagger API Documentation:** Open [http://localhost:8000/docs](http://localhost:8000/docs) in your browser.
- **Health Check Endpoint:** Open [http://localhost:8000/health](http://localhost:8000/health).

---

## API Usage Examples

### 1. Extract Invoice Data (`POST /extract-invoice`)

Upload a PDF or image file (e.g., Shore Point or Icarus invoice):

```bash
curl -X POST "http://localhost:8000/extract-invoice" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@/path/to/invoice_sample.pdf"
```
