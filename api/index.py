"""
TestPilot AI — Serverless Web API & Application Handler.

Compatible with both Vercel Serverless Functions and standalone local execution.
Reuses existing TestPilot agents, models, and execution engine directly.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure testpilot package is in sys.path
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Lazy imports of testpilot core to avoid top-level failures if environment is initializing
def _get_testpilot_modules():
    from testpilot.agents.analyzer import analyze_repository
    from testpilot.agents.executor import execute_tests
    from testpilot.agents.generator import generate_tests
    from testpilot.agents.repair import classify_failure_heuristically, run_repair_loop
    from testpilot.config import LLMProvider, Settings, load_settings
    from testpilot.evaluation.runner import run_benchmark_evaluation
    from testpilot.llm.client import LLMClientFactory

    return {
        "analyze_repository": analyze_repository,
        "execute_tests": execute_tests,
        "generate_tests": generate_tests,
        "classify_failure_heuristically": classify_failure_heuristically,
        "run_repair_loop": run_repair_loop,
        "run_benchmark_evaluation": run_benchmark_evaluation,
        "LLMProvider": LLMProvider,
        "Settings": Settings,
        "load_settings": load_settings,
        "LLMClientFactory": LLMClientFactory,
    }


def resolve_repo_path(raw_path: str | None) -> Path:
    """Safely resolve repository path against known presets or local filesystem."""
    if not raw_path or raw_path.strip() in ("", "."):
        # Default to python_simple benchmark if available, otherwise repo root
        preset = BASE_DIR / "benchmarks" / "repositories" / "python_simple"
        if preset.exists():
            return preset
        return BASE_DIR

    clean_path = raw_path.strip().replace("\\", "/")

    # Check known aliases
    if clean_path in ("python_simple", "benchmarks/repositories/python_simple"):
        p = BASE_DIR / "benchmarks" / "repositories" / "python_simple"
        if p.exists():
            return p.resolve()

    if clean_path in ("python_defect", "benchmarks/repositories/python_defect"):
        p = BASE_DIR / "benchmarks" / "repositories" / "python_defect"
        if p.exists():
            return p.resolve()

    if clean_path in ("self", "testpilot-ai", "."):
        return BASE_DIR.resolve()

    # Absolute path check
    p = Path(raw_path)
    if p.is_absolute() and p.exists() and p.is_dir():
        return p.resolve()

    # Relative to project base
    p_base = (BASE_DIR / raw_path).resolve()
    if p_base.exists() and p_base.is_dir():
        return p_base

    # Relative to current working directory
    p_cwd = (Path.cwd() / raw_path).resolve()
    if p_cwd.exists() and p_cwd.is_dir():
        return p_cwd

    raise FileNotFoundError(
        f"Repository path '{raw_path}' could not be resolved. "
        "Please select one of the bundled presets (e.g. python_simple) or enter an existing local directory."
    )


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):
    """Vercel serverless function & local HTTP request handler."""

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, message: str, status: int = 400, details: str = "") -> None:
        self._send_json(
            {
                "success": False,
                "error": message,
                "details": details,
            },
            status=status,
        )

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        url_path = self.path.split("?")[0].rstrip("/")
        if not url_path:
            url_path = "/"

        # API Routes
        if url_path in ("/api/health", "api/health"):
            self._handle_health()
            return

        if url_path in ("/api/presets", "api/presets"):
            self._handle_presets()
            return

        # Static file fallback for local standalone runner
        self._handle_static(url_path)

    def do_POST(self) -> None:
        url_path = self.path.split("?")[0].rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        body: dict[str, Any] = {}
        if content_length > 0:
            try:
                raw_body = self.rfile.read(content_length).decode("utf-8")
                body = json.loads(raw_body)
            except Exception as exc:
                self._send_error(f"Malformed JSON body: {exc}", status=400)
                return

        try:
            if url_path in ("/api/analyze", "api/analyze"):
                self._handle_analyze(body)
            elif url_path in ("/api/execute", "api/execute"):
                self._handle_execute(body)
            elif url_path in ("/api/generate", "api/generate"):
                self._handle_generate(body)
            elif url_path in ("/api/diagnose", "api/diagnose"):
                self._handle_diagnose(body)
            elif url_path in ("/api/repair", "api/repair"):
                self._handle_repair(body)
            elif url_path in ("/api/benchmark", "api/benchmark"):
                self._handle_benchmark(body)
            else:
                self._send_error(f"Unknown endpoint: {url_path}", status=404)
        except Exception as exc:
            trace = traceback.format_exc()
            self._send_error(str(exc), status=500, details=trace)

    # -----------------------------------------------------------------------
    # Route Handlers
    # -----------------------------------------------------------------------
    def _handle_health(self) -> None:
        tp = _get_testpilot_modules()
        settings = tp["load_settings"]()

        self._send_json(
            {
                "success": True,
                "status": "online",
                "app": "TestPilot AI",
                "version": "0.1.0",
                "platform": sys.platform,
                "python_version": sys.version.split()[0],
                "llm_provider": settings.llm_provider.value,
                "llm_model": settings.effective_llm_model,
                "openai_configured": settings.is_openai_configured(),
            }
        )

    def _handle_presets(self) -> None:
        presets = [
            {
                "id": "python_simple",
                "name": "Python Simple (Calculator Benchmark)",
                "path": "benchmarks/repositories/python_simple",
                "description": "Standard multi-module repository (arithmetic, statistics, converter) with 29 passing pytest tests & 91% coverage.",
                "type": "passing_suite",
                "tests_expected": 29,
                "recommended": True,
            },
            {
                "id": "python_defect",
                "name": "Python Defect (Failure Diagnosis Benchmark)",
                "path": "benchmarks/repositories/python_defect",
                "description": "Engineered test scenario to showcase TestPilot failure diagnosis, AST classification, and safety gate verification.",
                "type": "defect_benchmark",
                "tests_expected": 1,
                "recommended": False,
            },
            {
                "id": "self",
                "name": "TestPilot AI (Self Core Codebase)",
                "path": ".",
                "description": "TestPilot AI's own full platform codebase containing 342 automated unit tests across all agents.",
                "type": "full_platform",
                "tests_expected": 342,
                "recommended": False,
            },
        ]
        self._send_json({"success": True, "presets": presets})

    def _handle_analyze(self, body: dict[str, Any]) -> None:
        tp = _get_testpilot_modules()
        repo_path_str = body.get("repo_path")
        no_coverage = bool(body.get("no_coverage", False))

        repo_path = resolve_repo_path(repo_path_str)
        settings = tp["load_settings"]()

        analysis = tp["analyze_repository"](
            repo_path=repo_path,
            settings=settings,
            attempt_coverage=not no_coverage,
        )

        data = analysis.model_dump(mode="json")
        # Augment with computed properties for easy frontend access
        data["source_file_count"] = analysis.source_file_count
        data["test_file_count"] = analysis.test_file_count
        data["symbol_count"] = analysis.symbol_count
        data["public_symbol_count"] = len(analysis.public_symbols)
        data["has_tests"] = analysis.has_tests

        self._send_json({"success": True, "analysis": data})

    def _handle_execute(self, body: dict[str, Any]) -> None:
        tp = _get_testpilot_modules()
        repo_path_str = body.get("repo_path")
        no_coverage = bool(body.get("no_coverage", False))
        timeout = float(body.get("timeout", 60.0))

        repo_path = resolve_repo_path(repo_path_str)
        settings = tp["load_settings"]()

        report = tp["execute_tests"](
            repo_path=repo_path,
            settings=settings,
            with_coverage=not no_coverage,
            timeout=timeout,
            extra_args=["-o", "cache_dir=/tmp/.pytest_cache"],
        )

        data = report.model_dump(mode="json")
        data["has_failures"] = report.has_failures
        data["is_successful"] = report.success and not report.has_failures
        data["failed_tests_count"] = len(report.failed_tests)
        data["passed_tests_count"] = report.passed_count
        data["failed_tests"] = report.failed_tests

        self._send_json({"success": True, "execution": data})

    def _handle_generate(self, body: dict[str, Any]) -> None:
        tp = _get_testpilot_modules()
        repo_path_str = body.get("repo_path")
        target_file = body.get("target_file")
        api_key = body.get("openai_api_key", "").strip()

        repo_path = resolve_repo_path(repo_path_str)
        settings = tp["load_settings"]()

        if api_key:
            settings.openai_api_key = api_key
            settings.llm_provider = tp["LLMProvider"].OPENAI

        llm_client = tp["LLMClientFactory"].from_settings(settings)

        report = tp["generate_tests"](
            repo_path=repo_path,
            target_file=Path(target_file) if target_file else None,
            llm_client=llm_client,
            settings=settings,
            write_to_disk=False,  # Safe read-only demo mode
        )

        data = report.model_dump(mode="json")
        data["has_valid_tests"] = report.has_valid_tests
        data["total_tests_generated"] = report.total_tests_generated

        self._send_json({"success": True, "generation": data})

    def _handle_diagnose(self, body: dict[str, Any]) -> None:
        tp = _get_testpilot_modules()
        ftype = body.get("failure_type", "")
        fmsg = body.get("failure_message", "")
        traceback_str = body.get("traceback", "")

        category, explanation, is_repairable = tp["classify_failure_heuristically"](
            failure_type=ftype,
            failure_message=fmsg,
            traceback_str=traceback_str,
        )

        self._send_json(
            {
                "success": True,
                "category": category.value,
                "explanation": explanation,
                "is_repairable": is_repairable,
            }
        )

    def _handle_repair(self, body: dict[str, Any]) -> None:
        tp = _get_testpilot_modules()
        repo_path_str = body.get("repo_path")
        test_file = body.get("test_file")
        max_attempts = int(body.get("max_attempts", 2))
        api_key = body.get("openai_api_key", "").strip()

        repo_path = resolve_repo_path(repo_path_str)
        settings = tp["load_settings"]()

        if api_key:
            settings.openai_api_key = api_key
            settings.llm_provider = tp["LLMProvider"].OPENAI

        llm_client = tp["LLMClientFactory"].from_settings(settings)

        report = tp["run_repair_loop"](
            repo_path=repo_path,
            test_file=Path(test_file) if test_file else None,
            llm_client=llm_client,
            settings=settings,
            max_iterations=max_attempts,
            write_to_disk=False,
        )

        data = report.model_dump(mode="json")
        data["resolved"] = report.resolved
        data["failures_fixed_count"] = report.failures_fixed_count

        self._send_json({"success": True, "repair": data})

    def _handle_benchmark(self, body: dict[str, Any]) -> None:
        tp = _get_testpilot_modules()
        repo_path_str = body.get("repo_path")
        target_module = body.get("target_module")
        api_key = body.get("openai_api_key", "").strip()

        repo_path = resolve_repo_path(repo_path_str)
        settings = tp["load_settings"]()

        if api_key:
            settings.openai_api_key = api_key
            settings.llm_provider = tp["LLMProvider"].OPENAI

        llm_client = tp["LLMClientFactory"].from_settings(settings)

        result = tp["run_benchmark_evaluation"](
            repo_path=repo_path,
            target_module=target_module,
            llm_client=llm_client,
            settings=settings,
            isolate=True,
            write_to_disk=True,
        )

        data = result.model_dump(mode="json")
        self._send_json({"success": True, "benchmark": data})

    def _handle_static(self, path: str) -> None:
        """Serve built frontend static files from dist directory for local runs."""
        dist_dir = BASE_DIR / "dist"
        if not dist_dir.exists():
            # Send helpful fallback page if frontend not yet built
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head>
    <title>TestPilot AI — Demo Server</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b0f19; color: #f1f5f9; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 32px; max-width: 520px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }
        h1 { color: #38bdf8; margin-top: 0; font-size: 24px; display: flex; align-items: center; gap: 8px; }
        p { color: #94a3b8; line-height: 1.6; }
        code { background: #0f172a; color: #38bdf8; padding: 3px 8px; border-radius: 6px; font-size: 14px; }
        .btn { display: inline-block; margin-top: 16px; background: #0284c7; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; }
    </style>
</head>
<body>
    <div class="card">
        <h1>[TestPilot AI] API Server Ready</h1>
        <p>The Python backend API is active on port 8000.</p>
        <p>To view the full Web UI, compile the frontend assets by running:</p>
        <p><code>npm run build</code></p>
        <p>Or run the Vite development server with live reload:</p>
        <p><code>npm run dev</code></p>
        <a class="btn" href="/api/health">Check API Health &rarr;</a>
    </div>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))
            return

        # Clean requested path
        clean = path.lstrip("/")
        if not clean or clean == "/":
            file_path = dist_dir / "index.html"
        else:
            file_path = dist_dir / clean

        # SPA routing: if path doesn't exist, serve index.html
        if not file_path.exists() or file_path.is_dir():
            file_path = dist_dir / "index.html"

        if not file_path.exists():
            self.send_response(404)
            self.end_headers()
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error reading static file: {exc}".encode("utf-8"))


# Standalone runner
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"TestPilot AI Server running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()
