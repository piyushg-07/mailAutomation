"""
engine.py — Email validation, CSV parsing, templates, helpers. All in one.

Validation Pipeline:
  Layer 1: Syntax (RFC compliance)
  Layer 2: MX/DNS check (domain can receive mail)
  Layer 3: Disposable domain filter
  Layer 4: MyEmailVerifier API (actual mailbox check, multi-key rotation)
"""

import re
import io
import csv
import random
import requests
import pandas as pd
from datetime import datetime
from email_validator import validate_email, EmailNotValidError
from config import (
    DISPOSABLE_DOMAINS, VERIFY_API_KEYS, VERIFY_LIMIT_PER_KEY,
    VERIFY_API_URL
)


# ═══════════════════════════════════════════════
# API KEY ROTATION
# ═══════════════════════════════════════════════

class APIKeyManager:
    """Rotates multiple MyEmailVerifier API keys. 90% limit per key."""

    def __init__(self, api_keys: list[str], limit_per_key: int = 90):
        self.keys = [k.strip() for k in api_keys if k and k.strip()]
        self.limit = limit_per_key
        self.usage = {k: 0 for k in self.keys}
        self._idx = 0

    @property
    def available(self) -> bool:
        return any(self.usage[k] < self.limit for k in self.keys) if self.keys else False

    def get_key(self) -> str | None:
        if not self.keys:
            return None
        for _ in range(len(self.keys)):
            key = self.keys[self._idx]
            if self.usage[key] < self.limit:
                return key
            self._idx = (self._idx + 1) % len(self.keys)
        return None

    def record_use(self, key: str):
        if key in self.usage:
            self.usage[key] += 1
            if self.usage[key] >= self.limit:
                self._idx = (self._idx + 1) % len(self.keys)

    def get_remaining(self) -> int:
        return sum(max(0, self.limit - self.usage[k]) for k in self.keys)

def _check_single_credit(key: str) -> dict:
    """Helper to check one key's balance with 90s timeout."""
    try:
        url = f"https://client.myemailverifier.com/verifier/getcredits/{key}"
        # Setting 90s timeout because Free Tier queries are heavily delayed internally by their proxy
        resp = requests.get(url, timeout=90)
        if resp.status_code == 200:
            data = resp.json()
            if str(data.get("status", "")).lower() == "true":
                return {"key": key, "valid": True, "credits": int(data.get("credits", 0))}
            else:
                return {"key": key, "valid": False, "error": data.get("Message", "Invalid key response")}
        else:
            return {"key": key, "valid": False, "error": f"API Status: {resp.status_code}"}
    except requests.Timeout:
        return {"key": key, "valid": False, "error": "Timeout (API took >90s)"}
    except Exception as e:
        return {"key": key, "valid": False, "error": f"{type(e).__name__}: {str(e)}"}

def get_all_api_credits(api_keys: list[str]) -> list[dict]:
    """Fetch live credit balance for all API keys concurrently."""
    import concurrent.futures
    valid_keys = list(set([k.strip() for k in api_keys if k and k.strip()]))
    results = []
    
    # We call them simultaneously to bypass stacking 50s + 50s + 50s waits
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(valid_keys) or 1) as executor:
        future_to_key = {executor.submit(_check_single_credit, key): key for key in valid_keys}
        for future in concurrent.futures.as_completed(future_to_key):
            results.append(future.result())
            
    return results


# ═══════════════════════════════════════════════
# EMAIL VALIDATION
# ═══════════════════════════════════════════════

def _is_disposable(email: str) -> bool:
    try:
        return email.split("@")[1].lower().strip() in DISPOSABLE_DOMAINS
    except (IndexError, AttributeError):
        return False


def _verify_via_api(email: str, km: APIKeyManager) -> tuple[str, str | None]:
    """
    Check mailbox via MyEmailVerifier API.
    Returns: (status, reason)
      status: "valid" | "invalid" | "catch_all" | "unknown" | "skipped"
    """
    api_key = km.get_key()
    if not api_key:
        return "skipped", "All API keys exhausted"

    try:
        resp = requests.get(f"{VERIFY_API_URL}/{email}/{api_key}", timeout=15)

        if resp.status_code == 429:
            km.usage[api_key] = km.limit  # mark exhausted
            return _verify_via_api(email, km)  # try next key

        if resp.status_code != 200:
            # Often out of credits returns 401, 402, 403, etc.
            if resp.status_code in (401, 402, 403) or "credit" in resp.text.lower() or "limit" in resp.text.lower():
                km.usage[api_key] = km.limit  # mark exhausted
                return _verify_via_api(email, km)  # try next key
            return "unknown", f"API status {resp.status_code}"

        data = resp.json()
        status = str(data.get("Status", "")).strip().lower()
        message = str(data.get("Message", "")).lower() + str(data.get("Error", "")).lower()

        # If API says successful but body has an error about credits
        if status == "error" and ("credit" in message or "limit" in message or "exhausted" in message):
            km.usage[api_key] = km.limit  # mark exhausted
            return _verify_via_api(email, km)  # try next key

        km.record_use(api_key)

        if status == "valid":
            return "valid", None
        elif status == "invalid":
            return "invalid", f"Mailbox does not exist ({data.get('Diagnosis', 'rejected')})"
        elif status in ("catch all", "catch-all", "catchall"):
            return "catch_all", None
        elif status in ("grey-listed", "greylisted"):
            return "unknown", "Greylisted (try later)"
        else:
            return "unknown", f"Status: {status}"

    except requests.Timeout:
        return "unknown", "API timed out"
    except requests.ConnectionError:
        return "unknown", "Cannot reach API"
    except Exception as e:
        return "unknown", f"API error: {str(e)}"


def validate_single_email(email: str, km: APIKeyManager | None = None) -> dict:
    """Validate one email through 4-layer pipeline."""
    email = email.strip()
    result = {"email": email, "normalized": None, "valid": False, "reason": None, "api_status": None}

    if not email:
        result["reason"] = "Empty email"
        return result

    # Layer 1 & 2: Syntax + DNS/MX
    try:
        info = validate_email(email, check_deliverability=True)
        result["normalized"] = info.normalized
    except EmailNotValidError as e:
        msg = str(e)
        if "dns" in msg.lower() or "mx" in msg.lower():
            result["reason"] = "Domain cannot receive mail"
        elif "syntax" in msg.lower() or "not valid" in msg.lower():
            result["reason"] = "Invalid email syntax"
        else:
            result["reason"] = msg
        return result

    # Layer 3: Disposable filter
    if _is_disposable(result["normalized"]):
        result["reason"] = "Disposable/throwaway email"
        return result

    # Layer 4: API verification
    if km and km.available:
        api_status, api_reason = _verify_via_api(result["normalized"], km)
        result["api_status"] = api_status
        if api_status == "invalid":
            result["reason"] = api_reason
            return result
        elif api_status == "unknown":
            result["reason"] = api_reason # Save the network/API error so we can see it

    else:
        result["api_status"] = "skipped"
        result["reason"] = "No API keys available in config.py or daily limit reached"

    result["valid"] = True
    return result


def validate_email_list(emails: list[str], api_keys: list[str] | None = None,
                        progress_callback=None) -> tuple[list[dict], list[dict], int]:
    """Validate list of emails. Returns (valid, invalid, duplicates_removed)."""
    keys = api_keys or VERIFY_API_KEYS
    km = APIKeyManager(keys, VERIFY_LIMIT_PER_KEY) if keys else None

    valid, invalid, seen, unique, dupes = [], [], set(), [], 0
    for e in emails:
        low = e.strip().lower()
        if low and low not in seen:
            seen.add(low)
            unique.append(e.strip())
        elif low:
            dupes += 1

    for i, email in enumerate(unique):
        r = validate_single_email(email, km)
        (valid if r["valid"] else invalid).append(r)
        if progress_callback:
            progress_callback(i + 1, len(unique), r)

    return valid, invalid, dupes


# ═══════════════════════════════════════════════
# CSV PARSER (expects: email, name, company)
# ═══════════════════════════════════════════════

SAMPLE_CSV = "email,name,company\njohn@example.com,John Doe,Acme Corp\njane@example.com,Jane Smith,Widget Inc\n"


def get_sample_csv_bytes() -> bytes:
    """Returns sample CSV template as bytes for download."""
    return SAMPLE_CSV.encode("utf-8")


def parse_csv(file_content: bytes | io.BytesIO) -> dict:
    """Parse CSV with columns: email, name, company."""
    result = {"success": False, "error": None, "recipients": [], "preview_df": None}

    try:
        if isinstance(file_content, bytes):
            file_content = io.BytesIO(file_content)
        for enc in ["utf-8", "latin-1", "cp1252"]:
            try:
                file_content.seek(0)
                df = pd.read_csv(file_content, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            result["error"] = "Cannot decode CSV. Please use UTF-8."
            return result
    except pd.errors.EmptyDataError:
        result["error"] = "CSV is empty."
        return result
    except Exception as e:
        result["error"] = f"CSV error: {str(e)}"
        return result

    if df.empty:
        result["error"] = "CSV has no data rows."
        return result

    # Normalize column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    if "email" not in df.columns:
        result["error"] = f"No 'email' column found. Your CSV must have an 'email' column.\nFound: {', '.join(df.columns)}"
        return result

    df["email"] = df["email"].astype(str).str.strip().str.lower()
    df = df[df["email"].notna() & (df["email"] != "") & (df["email"] != "nan")]
    df = df.drop_duplicates(subset=["email"], keep="first")

    for _, row in df.iterrows():
        result["recipients"].append({
            "email": row["email"],
            "name": str(row.get("name", "")).strip() if pd.notna(row.get("name")) and str(row.get("name")) != "nan" else "",
            "company": str(row.get("company", "")).strip() if pd.notna(row.get("company")) and str(row.get("company")) != "nan" else "",
        })

    result["success"] = True
    result["preview_df"] = df.head(10)
    return result


def parse_manual_emails(text: str) -> list[dict]:
    """Parse pasted emails (comma/newline/space separated)."""
    if not text or not text.strip():
        return []
    seen, out = set(), []
    for email in re.split(r'[,;\n\r\s]+', text.strip()):
        email = email.strip().lower()
        if email and email not in seen:
            seen.add(email)
            out.append({"email": email, "name": "", "company": ""})
    return out


# ═══════════════════════════════════════════════
# TEMPLATE ENGINE (User-Provided)
# ═══════════════════════════════════════════════

def pick_random_template(templates: list[dict], placeholders: dict) -> tuple[str, str, str]:
    """
    Pick a random template from user-provided list and render placeholders.

    Args:
        templates: List of dicts, each with keys "subject" and "body".
        placeholders: Dict of placeholder values, e.g. {"name": "...", "company": "..."}.

    Returns:
        (rendered_subject, rendered_body, template_label)
    """
    if not templates:
        raise ValueError("No email templates configured. Add at least one template.")

    idx = random.randint(0, len(templates) - 1)
    chosen = templates[idx]
    label = f"Template {idx + 1}"

    placeholders["date"] = datetime.now().strftime("%B %d, %Y")

    subject = chosen.get("subject", "")
    body = chosen.get("body", "")

    for k, v in placeholders.items():
        val = str(v) if v else ""
        subject = subject.replace(f"{{{k}}}", val)
        body = body.replace(f"{{{k}}}", val)

    # Clean any unfilled placeholders
    subject = re.sub(r'\{[a-zA-Z_]+\}', '', subject).strip()
    body = re.sub(r'\{[a-zA-Z_]+\}', '', body)
    body = re.sub(r'  +', ' ', body).strip()

    return subject, body, label


# ═══════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════

def export_report_csv(results: dict) -> bytes:
    """Generate CSV report from send results."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Email", "Status", "Detail", "Time"])
    for s in results.get("sent", []):
        w.writerow([s["email"], "Sent", s.get("template", ""), s.get("timestamp", "")])
    for f in results.get("failed", []):
        w.writerow([f["email"], "Failed", f.get("error", ""), f.get("timestamp", "")])
    return out.getvalue().encode("utf-8")


def format_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60: return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s"
