# Deployment Guide — FastAPI Backend & Streamlit Dashboard on Render

This project contains two separate, decoupled microservices:
1. **FastAPI Backend**: Handles AI Vision extraction (Mistral, Groq, OpenRouter), automatic provider failover, mathematical verification, Excel generation, and encrypted API key management.
2. **Streamlit Frontend**: Provides the interactive 2-panel web dashboard (Sidebar API key management + Right panel multi-PDF upload, live progress, audit results, and chatbot).

---

## Architecture Overview

```
                      ┌─────────────────────────────────────────┐
                      │    Streamlit Dashboard (Frontend)      │
                      │  Port: $PORT (Web Service on Render)    │
                      └────────────────────┬────────────────────┘
                                           │
                           REST API Calls  │ (BACKEND_URL)
                                           ▼
                      ┌─────────────────────────────────────────┐
                      │      FastAPI Backend (Extraction Engine) │
                      │  Port: $PORT (Web Service on Render)    │
                      └────────┬───────────┬───────────┬────────┘
                               │           │           │
                     Failover  ▼           ▼           ▼
                           Mistral    OpenRouter     Groq
```

---

## 1. Deploying to Render via Blueprint (Recommended)

1. Push your repository to **GitHub** or **GitLab**.
2. Log in to [Render](https://dashboard.render.com).
3. Click **New +** -> **Blueprint**.
4. Select your repository containing [`render.yaml`](file:///c:/Purchase%20inventory/render.yaml).
5. Render will automatically configure both services:
   - `purchase-inventory-backend`: FastAPI running on Uvicorn.
   - `purchase-inventory-dashboard`: Streamlit frontend with automatic `BACKEND_URL` injection.
6. Under **Environment Variables**:
   - `DASHBOARD_PASSWORD`: Your chosen admin password to access the dashboard (default: `admin123`).
   - `MISTRAL_API_KEY`: Initial Mistral key (or configure it directly from the UI sidebar later).
7. Click **Apply**. Both services will build and deploy independently.

---

## 2. Manual Render Deployment (Alternative)

### Step A: Deploy FastAPI Backend
1. Click **New +** -> **Web Service**.
2. Connect your repo and set:
   - **Name**: `purchase-inventory-backend`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. Add Environment Variables:
   - `DASHBOARD_PASSWORD`: `<your-secure-password>`
   - `MISTRAL_API_KEY`: `<your-mistral-api-key>`
   - `MISTRAL_VISION_MODEL`: `pixtral-12b-2409`
4. Deploy and copy the assigned backend URL (e.g. `https://purchase-inventory-backend.onrender.com`).

### Step B: Deploy Streamlit Frontend
1. Click **New +** -> **Web Service**.
2. Connect the same repo and set:
   - **Name**: `purchase-inventory-dashboard`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
3. Add Environment Variables:
   - `BACKEND_URL`: `https://purchase-inventory-backend.onrender.com` (use your Step A backend URL)
4. Deploy. Open your Streamlit URL to access the live dashboard!

---

## 3. Local Development & Testing

### Running the Backend:
```bash
.\venv\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8000 --reload
```

### Running the Streamlit Dashboard:
```bash
$env:BACKEND_URL="http://127.0.0.1:8000"
.\venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8501
```

Access the UI at: `http://localhost:8501` (Dashboard Password default: `admin123`).
Access the FastAPI docs at: `http://localhost:8000/docs`.

---

## 4. Key Management & Failover Features
- **Zero Frontend Exposure**: Keys are stored exclusively on the backend in encrypted format (`temp/api_keys.enc`) and never leaked to browser local storage or client scripts.
- **Provider Switching**: Users can switch preferred active providers (`Mistral AI`, `Groq`, `OpenRouter`) directly from the sidebar UI without touching code or redeploying on Render.
- **Automatic Failover**: If the active provider encounters HTTP 429 (Rate Limit Exceeded), 401 (Invalid Key), or 402 (Quota Exhausted), the backend seamlessly routes extraction to the next configured provider in the failover chain.
