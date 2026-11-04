#!/usr/bin/env python3
"""QuoteClarify: local HTTP + static UI. Python 3.9+, no third-party dependencies."""
import concurrent.futures
import copy
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import threading
import uuid
from urllib.parse import urlsplit

from client import ApiError, ClockedClient
from core import InputError, analyze_case, export_text, require_string, validate_input

APP = Path(__file__).resolve().parent
STATE = APP / ".local"
WEB = APP / "web"
FIXTURES = APP / "examples"


class Service:
    def __init__(self, state_dir=STATE, api_client=None):
        self.state_dir = Path(state_dir)
        self.jobs_dir, self.analyses_dir = self.state_dir / "jobs", self.state_dir / "analyses"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.analyses_dir.mkdir(parents=True, exist_ok=True)
        self.client = api_client or ClockedClient(self.state_dir / "api")
        self.lock = threading.RLock()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        for path in self.jobs_dir.glob("*.json"):
            job = json.loads(path.read_text())
            if job["status"] in ("queued", "running"):
                job.update(status="failed", stage="failed", error={"code": "server_restarted",
                    "message": "The local server restarted. Existing completed results are retained; no new model request was sent automatically.", "retryable": False})
                self._save(path, job)

    def _save(self, path, value):
        with self.lock:
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            os.replace(str(temp), str(path))

    def _load(self, folder, identifier):
        try:
            uuid.UUID(identifier)
        except (ValueError, TypeError, AttributeError):
            raise KeyError("Unknown identifier.")
        path = folder / (identifier + ".json")
        with self.lock:
            if not path.exists():
                raise KeyError("Unknown identifier.")
            return json.loads(path.read_text())

    def analysis(self, identifier):
        return self._load(self.analyses_dir, identifier)

    def job(self, identifier):
        return self._load(self.jobs_dir, identifier)

    def status(self):
        with self.lock:
            pending = sum(json.loads(p.read_text())["status"] in ("queued", "running")
                          for p in self.jobs_dir.glob("*.json"))
        return {"configured": self.client.configured, "budget": self.client.budget(),
            "pendingJobs": pending, "externalMode": "live", "cashOverageEnabled": False}

    def submit(self, request, base=None):
        value = validate_input(request)
        if not self.client.configured:
            raise ApiError("not_configured", "Configure the local backend API key before analyzing.")
        if self.status()["pendingJobs"] >= 2:
            raise ApiError("busy", "Two review jobs are already pending. Wait for them to finish.", True)
        identifier = str(uuid.uuid4())
        job = {"jobId": identifier, "status": "queued", "stage": "queued", "progress": [],
            "error": None, "result": None}
        path = self.jobs_dir / (identifier + ".json")
        self._save(path, job)

        def work():
            job.update(status="running")
            self._save(path, job)

            def progress(endpoint, meta):
                job["stage"] = endpoint
                if meta is not None:
                    job["progress"].append(meta)
                self._save(path, job)
            try:
                result = analyze_case(value, self.client, progress, base=base)
                self._save(self.analyses_dir / (result["analysisId"] + ".json"), result)
                job.update(status="succeeded", stage="complete", result=result)
            except ApiError as error:
                job.update(status="failed", stage="failed", error={"code": error.code,
                    "message": error.message, "retryable": error.retryable})
            except Exception as error:
                job.update(status="failed", stage="failed", error={"code": "invalid_upstream_result",
                    "message": str(error)[:600], "retryable": False})
            self._save(path, job)

        self.executor.submit(work)
        return {"jobId": identifier, "status": "queued", "pollUrl": "/api/jobs/" + identifier}

    def verify(self, body):
        if not isinstance(body, dict) or set(body) != {"analysisId", "expectedRevision", "draftSummary"}:
            raise InputError("Verify requires analysisId, expectedRevision and draftSummary only.")
        base = self.analysis(body["analysisId"])
        if body["expectedRevision"] != base["revision"]:
            raise ApiError("stale_analysis", "The selected analysis revision no longer matches.")
        require_string(body["draftSummary"], "draftSummary", 2000)
        value = copy.deepcopy(base["input"])
        value["draftSummary"] = body["draftSummary"]
        return self.submit(value, base=base)

    def export(self, body):
        if not isinstance(body, dict) or set(body) != {"analysisId", "expectedRevision", "input"}:
            raise InputError("Export requires analysisId, expectedRevision and the current input only.")
        result = self.analysis(body["analysisId"])
        try:
            return export_text(result, body["input"], body["expectedRevision"])
        except InputError as error:
            raise ApiError("stale_analysis", str(error))


def examples():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    output = []
    for case in manifest["cases"]:
        names = [case["rfq"]] + case["quotations"]
        texts = []
        for name in names:
            path = (FIXTURES / name).resolve()
            if FIXTURES.resolve() not in path.parents or not path.is_file():
                raise ValueError("Invalid example allowlist path.")
            # newline='' preserves CRLF and therefore source offsets.
            with path.open(encoding="utf-8", newline="") as handle:
                texts.append(handle.read())
        value = {"rfq": {"id": "rfq", "title": "Buyer RFQ", "text": texts[0]},
            "quotes": [{"id": "quote-a", "title": "Quotation A", "supplier": "Supplier A", "text": texts[1]},
                {"id": "quote-b", "title": "Quotation B", "supplier": "Supplier B", "text": texts[2]}],
            "focus": "Which price basis, quantities, delivery conditions, payment and exclusions need buyer clarification?",
            "draftSummary": ""}
        validate_input(value)
        output.append({"id": case["id"], "title": case["id"].replace("-", " ").title(), "input": value})
    return {"synthetic": True, "examples": output}


class Handler(BaseHTTPRequestHandler):
    server_version = "QuoteClarify/0.1"

    def _json(self, status, value):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, code, message, retryable=False):
        self._json(status, {"error": {"code": code, "message": message, "retryable": retryable}})

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/api/health":
                return self._json(200, {"ok": True, "name": "QuoteClarify", "version": "0.1"})
            if path == "/api/status":
                return self._json(200, self.server.service.status())
            if path == "/api/examples":
                return self._json(200, examples())
            if path.startswith("/api/jobs/"):
                return self._json(200, self.server.service.job(path.removeprefix("/api/jobs/")))
            if path.startswith("/api/analyses/"):
                return self._json(200, self.server.service.analysis(path.removeprefix("/api/analyses/")))
            if path.startswith("/api/"):
                return self._error(404, "not_found", "Unknown API route.")
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (WEB / relative).resolve()
            if WEB.resolve() not in target.parents or not target.is_file():
                return self._error(404, "not_found", "The UI file is not available yet.")
            content = target.read_bytes()
            self.send_response(200)
            mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
        except KeyError:
            self._error(404, "not_found", "The requested job or analysis does not exist.")
        except Exception:
            self._error(500, "server_error", "Could not load local review data.")

    def do_POST(self):
        origin = self.headers.get("Origin")
        port = self.server.server_port
        if origin and origin not in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port):
            return self._error(403, "origin_rejected", "Use the local application origin.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100000:
                return self._error(413, "invalid_size", "JSON request body must be between 1 and 100,000 bytes.")
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self._error(415, "json_required", "Send application/json.")
            body = json.loads(self.rfile.read(length).decode("utf-8"),
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON value")))
            path = urlsplit(self.path).path
            if path == "/api/analyze":
                return self._json(202, self.server.service.submit(body))
            if path == "/api/verify":
                return self._json(202, self.server.service.verify(body))
            if path == "/api/export":
                return self._json(200, self.server.service.export(body))
            return self._error(404, "not_found", "Unknown API route.")
        except (InputError, ValueError, UnicodeError) as error:
            self._error(400, "invalid_input", str(error)[:600])
        except KeyError:
            self._error(404, "not_found", "The requested analysis does not exist.")
        except ApiError as error:
            status = {"stale_analysis": 409, "development_budget_exhausted": 402,
                "not_configured": 503, "busy": 429}.get(error.code, 502)
            self._error(status, error.code, error.message, error.retryable)
        except Exception:
            self._error(500, "server_error", "Could not process the local review request.")

    def log_message(self, fmt, *args):
        # HTTP paths only, never request bodies or authorization headers.
        print("%s %s" % (datetime.datetime.now().isoformat(timespec="seconds"), fmt % args), flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8190), Handler)
    server.service = Service()
    print("QuoteClarify listening at http://127.0.0.1:8190 (localhost only; overage off)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.service.executor.shutdown(wait=False)
