import os
import json
import time
import logging
import base64
import secrets
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, List

from config import TEMP_DIR, MISTRAL_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY

logger = logging.getLogger("key_manager")

# Secure backend storage path
KEYS_ENC_PATH = TEMP_DIR / "api_keys.enc"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")

# Simple server-side key encryption helper using a backend secret
_SECRET_KEY = os.getenv("ENCRYPTION_KEY", "purchase-inventory-backend-secret-2026")


def _xor_cipher(data: str, key: str) -> str:
    return "".join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(data))


def _encrypt_payload(payload: Dict[str, Any]) -> str:
    raw_str = json.dumps(payload)
    xored = _xor_cipher(raw_str, _SECRET_KEY)
    return base64.b64encode(xored.encode("utf-8")).decode("ascii")


def _decrypt_payload(enc_str: str) -> Dict[str, Any]:
    try:
        xored = base64.b64decode(enc_str.encode("ascii")).decode("utf-8")
        raw_str = _xor_cipher(xored, _SECRET_KEY)
        return json.loads(raw_str)
    except Exception as e:
        logger.warning(f"Decryption error: {e}")
        return {}


# In-memory active authentication tokens
ACTIVE_TOKENS: Dict[str, float] = {}
TOKEN_EXPIRY_SECONDS = 86400 * 7  # 7 days

# Provider state cache
PROVIDER_STATUS: Dict[str, Dict[str, Any]] = {
    "mistral": {
        "status": "Not Configured",
        "error_message": None,
        "last_tested": None,
        "default_model": "pixtral-12b-2409",
        "display_name": "Mistral AI",
        "supports_vision": True
    },
    "groq": {
        "status": "Not Configured",
        "error_message": None,
        "last_tested": None,
        "default_model": "llama-3.2-11b-vision-preview",
        "display_name": "Groq",
        "supports_vision": True
    },
    "openrouter": {
        "status": "Not Configured",
        "error_message": None,
        "last_tested": None,
        "default_model": "google/gemini-2.0-flash-001",
        "display_name": "OpenRouter",
        "supports_vision": True
    }
}

_active_provider_preference: str = "mistral"


def _mask_key(key: str) -> str:
    """Masks API key for secure frontend display (e.g. mstrl_••••••••3ZDn)."""
    if not key:
        return ""
    if len(key) <= 8:
        return "••••••••"
    prefix = key[:6]
    suffix = key[-4:]
    return f"{prefix}••••••••{suffix}"


def load_keys() -> Dict[str, str]:
    """Loads API keys from backend encrypted store, seeding from config/.env or Streamlit secrets if not present."""
    global _active_provider_preference
    m_key = os.getenv("MISTRAL_API_KEY") or MISTRAL_API_KEY or ""
    g_key = os.getenv("GROQ_API_KEY") or GROQ_API_KEY or ""
    o_key = os.getenv("OPENROUTER_API_KEY") or OPENROUTER_API_KEY or ""

    try:
        import streamlit as _st
        if hasattr(_st, "secrets"):
            m_key = m_key or str(_st.secrets.get("MISTRAL_API_KEY", ""))
            g_key = g_key or str(_st.secrets.get("GROQ_API_KEY", ""))
            o_key = o_key or str(_st.secrets.get("OPENROUTER_API_KEY", ""))
    except Exception:
        pass

    keys: Dict[str, str] = {
        "mistral": m_key.strip(),
        "groq": g_key.strip(),
        "openrouter": o_key.strip()
    }

    if KEYS_ENC_PATH.exists():
        try:
            with open(KEYS_ENC_PATH, "r", encoding="utf-8") as f:
                saved = _decrypt_payload(f.read().strip())
                if isinstance(saved, dict):
                    for p in ["mistral", "groq", "openrouter"]:
                        if saved.get(p):
                            keys[p] = str(saved[p]).strip()
                    if saved.get("_active_provider"):
                        _active_provider_preference = saved["_active_provider"]
        except Exception as e:
            logger.warning(f"Failed to read secure keys store from {KEYS_ENC_PATH}: {e}")

    # Update provider status
    for p, k in keys.items():
        if k:
            if PROVIDER_STATUS[p]["status"] in ["Not Configured", "Unknown"]:
                PROVIDER_STATUS[p]["status"] = "Active"
        else:
            PROVIDER_STATUS[p]["status"] = "Not Configured"

    return keys


def save_key(provider: str, key_value: str) -> bool:
    """Securely encrypts and persists an API key on the backend."""
    provider = provider.lower().strip()
    if provider not in ["mistral", "groq", "openrouter"]:
        raise ValueError(f"Unsupported provider: '{provider}'")

    keys = load_keys()
    keys[provider] = key_value.strip()

    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        payload = dict(keys)
        payload["_active_provider"] = _active_provider_preference
        enc_data = _encrypt_payload(payload)
        with open(KEYS_ENC_PATH, "w", encoding="utf-8") as f:
            f.write(enc_data)

        PROVIDER_STATUS[provider]["status"] = "Active" if key_value.strip() else "Not Configured"
        PROVIDER_STATUS[provider]["error_message"] = None
        PROVIDER_STATUS[provider]["last_tested"] = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Encrypted and saved key for provider '{provider}' securely.")
        return True
    except Exception as e:
        logger.error(f"Failed to save key for {provider}: {e}")
        raise


def delete_key(provider: str) -> bool:
    """Deletes an API key for the specified provider."""
    provider = provider.lower().strip()
    if provider not in ["mistral", "groq", "openrouter"]:
        raise ValueError(f"Unsupported provider: '{provider}'")

    keys = load_keys()
    keys[provider] = ""

    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        payload = dict(keys)
        payload["_active_provider"] = _active_provider_preference
        enc_data = _encrypt_payload(payload)
        with open(KEYS_ENC_PATH, "w", encoding="utf-8") as f:
            f.write(enc_data)

        PROVIDER_STATUS[provider]["status"] = "Not Configured"
        PROVIDER_STATUS[provider]["error_message"] = None
        PROVIDER_STATUS[provider]["last_tested"] = None
        logger.info(f"Deleted key for provider '{provider}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to delete key for {provider}: {e}")
        raise


def get_key(provider: str) -> Optional[str]:
    """Retrieves plaintext key for backend execution only."""
    keys = load_keys()
    k = keys.get(provider.lower().strip())
    return k if k else None


def set_active_provider(provider: str) -> bool:
    """Sets the preferred active provider."""
    global _active_provider_preference
    provider = provider.lower().strip()
    if provider not in ["mistral", "groq", "openrouter"]:
        raise ValueError(f"Unsupported provider: '{provider}'")
    try:
        keys = load_keys()
        _active_provider_preference = provider
        payload = dict(keys)
        payload["_active_provider"] = _active_provider_preference
        with open(KEYS_ENC_PATH, "w", encoding="utf-8") as f:
            f.write(_encrypt_payload(payload))
        return True
    except Exception:
        return False


def get_active_provider() -> str:
    """Returns preferred active provider."""
    load_keys()
    return _active_provider_preference


def get_fallback_order() -> List[str]:
    """
    Returns ordered list of providers:
    preferred provider first, followed by remaining configured providers.
    """
    load_keys()
    preferred = _active_provider_preference
    all_providers = ["mistral", "openrouter", "groq"]
    order = [preferred] + [p for p in all_providers if p != preferred]
    # Filter to only providers that have a configured key
    configured = [p for p in order if get_key(p)]
    return configured if configured else order


def mark_provider_error(provider: str, error_msg: str, status_code: Optional[int] = None):
    """Flags a provider as rate-limited, quota exhausted, invalid key, or in error to trigger automatic failover."""
    provider = provider.lower().strip()
    if provider in PROVIDER_STATUS:
        msg_lower = error_msg.lower()
        if status_code == 401 or "unauthorized" in msg_lower or "invalid api key" in msg_lower:
            PROVIDER_STATUS[provider]["status"] = "Invalid Key"
        elif status_code == 429 or "rate limit" in msg_lower or "tpm" in msg_lower or "rpm" in msg_lower:
            PROVIDER_STATUS[provider]["status"] = "Rate Limit Exceeded"
        elif "quota" in msg_lower or "credits" in msg_lower or "balance" in msg_lower or "insufficient" in msg_lower:
            PROVIDER_STATUS[provider]["status"] = "Quota Exhausted"
        else:
            PROVIDER_STATUS[provider]["status"] = "Error"

        PROVIDER_STATUS[provider]["error_message"] = error_msg
        PROVIDER_STATUS[provider]["last_tested"] = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.warning(f"Provider '{provider}' status updated to '{PROVIDER_STATUS[provider]['status']}': {error_msg}")


def mark_provider_success(provider: str):
    """Marks a provider as Active following a successful call."""
    provider = provider.lower().strip()
    if provider in PROVIDER_STATUS:
        PROVIDER_STATUS[provider]["status"] = "Active"
        PROVIDER_STATUS[provider]["error_message"] = None
        PROVIDER_STATUS[provider]["last_tested"] = time.strftime("%Y-%m-%d %H:%M:%S")


def get_providers_overview() -> Dict[str, Any]:
    """Returns safe, masked provider info and health for frontend rendering."""
    keys = load_keys()
    overview = {
        "active_provider": _active_provider_preference,
        "providers": {}
    }
    for p in ["mistral", "groq", "openrouter"]:
        val = keys.get(p, "")
        state = dict(PROVIDER_STATUS[p])
        state["has_key"] = bool(val)
        state["masked_key"] = _mask_key(val)
        state["is_active_preference"] = (p == _active_provider_preference)
        overview["providers"][p] = state
    return overview


def test_provider_key(provider: str, custom_key: Optional[str] = None) -> Dict[str, Any]:
    """Tests connectivity and authentication for a given provider."""
    provider = provider.lower().strip()
    key_to_test = custom_key.strip() if custom_key else get_key(provider)

    if not key_to_test:
        return {
            "success": False,
            "provider": provider,
            "status": "Not Configured",
            "message": f"No API key provided or configured for {provider.capitalize()}."
        }

    test_urls = {
        "mistral": ("https://api.mistral.ai/v1/models", "Mistral AI"),
        "groq": ("https://api.groq.com/openai/v1/models", "Groq"),
        "openrouter": ("https://openrouter.ai/api/v1/auth/key", "OpenRouter")
    }

    if provider not in test_urls:
        return {"success": False, "provider": provider, "status": "Error", "message": f"Unknown provider: {provider}"}

    url, display_name = test_urls[provider]
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key_to_test}",
            "User-Agent": "PurchaseInventory/1.0"
        },
        method="GET"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                PROVIDER_STATUS[provider]["status"] = "Active"
                PROVIDER_STATUS[provider]["error_message"] = None
                PROVIDER_STATUS[provider]["last_tested"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return {
                    "success": True,
                    "provider": provider,
                    "status": "Active",
                    "message": f"Successfully authenticated with {display_name} API (HTTP 200 OK)."
                }
            else:
                msg = f"Unexpected response code: {resp.status}"
                PROVIDER_STATUS[provider]["status"] = "Error"
                PROVIDER_STATUS[provider]["error_message"] = msg
                return {"success": False, "provider": provider, "status": "Error", "message": msg}

    except urllib.error.HTTPError as he:
        err_body = ""
        try:
            err_body = he.read().decode("utf-8")
        except Exception:
            pass

        if he.code == 401:
            msg = f"Invalid API Key: 401 Unauthorized for {display_name}."
            stat = "Invalid Key"
        elif he.code == 429:
            msg = f"Rate Limit / Quota Exceeded (429) on {display_name}."
            stat = "Rate Limit Exceeded"
        elif he.code == 402:
            msg = f"Payment Required / Quota Exhausted on {display_name}."
            stat = "Quota Exhausted"
        else:
            msg = f"{display_name} returned HTTP {he.code}: {he.reason}"
            stat = "Error"

        PROVIDER_STATUS[provider]["status"] = stat
        PROVIDER_STATUS[provider]["error_message"] = msg
        PROVIDER_STATUS[provider]["last_tested"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return {"success": False, "provider": provider, "status": stat, "message": msg}

    except Exception as e:
        msg = f"Connection error testing {display_name}: {str(e)}"
        PROVIDER_STATUS[provider]["status"] = "Error"
        PROVIDER_STATUS[provider]["error_message"] = msg
        PROVIDER_STATUS[provider]["last_tested"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return {"success": False, "provider": provider, "status": "Error", "message": msg}


# -------------------------------------------------------------
# Dashboard Authentication Utilities
# -------------------------------------------------------------
def authenticate_user(password: str) -> Optional[str]:
    """Validates dashboard password and generates a session token."""
    if password == DASHBOARD_PASSWORD:
        token = secrets.token_hex(24)
        ACTIVE_TOKENS[token] = time.time() + TOKEN_EXPIRY_SECONDS
        return token
    return None


def validate_token(token: Optional[str]) -> bool:
    """Checks if a given session token is valid and unexpired."""
    if not token:
        return False
    expiry = ACTIVE_TOKENS.get(token)
    if expiry and expiry > time.time():
        return True
    if token in ACTIVE_TOKENS:
        del ACTIVE_TOKENS[token]
    return False
