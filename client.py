"""Small backend-only Clocked client with persistent identity, cache and credit ledger."""
import datetime
import hashlib
import json
import math
from pathlib import Path
import shlex
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid


class ApiError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


class ClockedClient:
    def __init__(self, state_dir, secret_path=None, limit=1000):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "api.sqlite3"
        self.limit = limit
        self.lock = threading.RLock()
        self.env = {}
        path = Path(secret_path or Path.home() / ".config/secrets/clocked.env")
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values = shlex.split(value)
                    self.env[key] = values[0] if values else ""
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (cache_key TEXT PRIMARY KEY, endpoint TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, response TEXT, meta TEXT, credits INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")

    def _db(self):
        return sqlite3.connect(str(self.db_path), timeout=10)

    @property
    def configured(self):
        return bool(self.env.get("CLOCKED_API_KEY"))

    def budget(self):
        with self._db() as db:
            used = db.execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0]
        return {"limitCredits": self.limit, "usedCredits": used,
                "remainingCredits": max(0, self.limit - used)}

    def call(self, endpoint, payload):
        if endpoint not in ("compare", "rerank", "grounding", "fill"):
            raise ApiError("unsupported_endpoint", "This application uses only Compare, Rerank, Fill and Verify.")
        if not self.configured:
            raise ApiError("not_configured", "The backend has no local Clocked API key. See setup instructions.")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        cache_key = hashlib.sha256((endpoint + "\n" + encoded).encode()).hexdigest()
        # Serialize calls: no unbounded fan-out or duplicate in-flight requests.
        with self.lock:
            with self._db() as db:
                row = db.execute("SELECT request_id,status,response,meta,credits FROM calls WHERE cache_key=?", (cache_key,)).fetchone()
                if row and row[1] == "succeeded":
                    meta = json.loads(row[3])
                    meta.update(transport="cache", credits=0, referenceCostUsd=0, elapsedMs=0)
                    return {"data": json.loads(row[2]), "meta": meta}
                if self.budget()["remainingCredits"] < 200:
                    raise ApiError("development_budget_exhausted", "Development credit reserve reached. No new model request was sent.")
                unknown = db.execute("SELECT cache_key FROM calls WHERE status='unknown' AND cache_key<>?", (cache_key,)).fetchone()
                if unknown:
                    raise ApiError("unknown_previous_request", "A prior request has an unknown billing outcome. Resolve it with its original request identity before starting new work.")
                request_id = row[0] if row and row[1] in ("pending", "unknown") else str(uuid.uuid4())
                db.execute("INSERT OR REPLACE INTO calls(cache_key,endpoint,request_id,payload,status,created_at) VALUES(?,?,?,?,?,?)",
                    (cache_key, endpoint, request_id, encoded, "pending", datetime.datetime.now(datetime.timezone.utc).isoformat()))
            headers = {"Authorization": "Bearer " + self.env["CLOCKED_API_KEY"],
                "Content-Type": "application/json", "Idempotency-Key": request_id}
            request = urllib.request.Request("https://clocked.rezolve.ai/clocked/" + endpoint,
                data=encoded.encode("utf-8"), headers=headers)
            started = time.monotonic()
            status, response_headers, response_text = None, {}, ""
            try:
                with urllib.request.urlopen(request, timeout=130) as response:
                    status, response_headers = response.status, response.headers
                    response_text = response.read().decode("utf-8")
            except urllib.error.HTTPError as error:
                status, response_headers = error.code, error.headers
                response_text = error.read().decode("utf-8", errors="replace")
            except Exception as error:
                with self._db() as db:
                    db.execute("UPDATE calls SET status='unknown' WHERE cache_key=?", (cache_key,))
                raise ApiError("unknown_network_outcome", "Request outcome is unknown; the original request ID was retained. " + type(error).__name__)
            elapsed = round((time.monotonic() - started) * 1000)
            try:
                raw = json.loads(response_text)
            except (ValueError, TypeError):
                raw = None
            try:
                settled_credits = int(response_headers.get("X-Clocked-Credits", "0"))
                reference = float(response_headers.get("X-Clocked-Cost-Usd", "0"))
                if settled_credits < 0 or not math.isfinite(reference) or reference < 0:
                    raise ValueError("Invalid debit")
            except (TypeError, ValueError):
                with self._db() as db:
                    db.execute("UPDATE calls SET status='unknown' WHERE cache_key=?", (cache_key,))
                raise ApiError("invalid_billing_receipt", "The API returned an invalid credit receipt. New requests are paused.")
            replay = response_headers.get("X-Clocked-Transport") == "replay"
            meta = {"endpoint": endpoint, "requestId": request_id,
                "transport": "replay" if replay else "live", "credits": 0 if replay else settled_credits,
                "referenceCostUsd": reference, "elapsedMs": elapsed,
                "costBasis": response_headers.get("X-Clocked-Cost-Basis"),
                "modelMs": response_headers.get("X-Clocked-Model-Ms"),
                "originalAccountCredits": settled_credits}
            # API outputs and IDs only; no Authorization/session headers are persisted.
            receipt = {"endpoint": endpoint, "requestId": request_id, "payload": payload,
                "status": status, "result": raw, "meta": meta}
            (self.state_dir / ("receipt-" + request_id + ".json")).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
            if status != 200 or not isinstance(raw, dict):
                unknown_outcome = (status == 409 or (status or 0) >= 500) and not (
                    isinstance(raw, dict) and raw.get("retryAsNew") is True)
                with self._db() as db:
                    db.execute("UPDATE calls SET status=?,response=?,meta=?,credits=? WHERE cache_key=?",
                        ("unknown" if unknown_outcome else "failed", json.dumps(raw), json.dumps(meta), settled_credits, cache_key))
                message = raw.get("error") if isinstance(raw, dict) else "The upstream response was not JSON."
                if not isinstance(message, str):
                    message = "The upstream API rejected this request."
                raise ApiError("upstream_%s" % status, message[:600], status == 429 or (status or 0) >= 500)
            # A valid trial response must disclose its debit. Unknown cost freezes further calls.
            if not response_headers.get("X-Clocked-Credits"):
                with self._db() as db:
                    db.execute("UPDATE calls SET status='unknown' WHERE cache_key=?", (cache_key,))
                raise ApiError("missing_billing_receipt", "The API returned no credit debit. Further new requests are paused.")
            with self._db() as db:
                db.execute("UPDATE calls SET status='succeeded',response=?,meta=?,credits=? WHERE cache_key=?",
                    (json.dumps(raw, ensure_ascii=False), json.dumps(meta), settled_credits, cache_key))
            return {"data": raw, "meta": meta}
