# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Centralized Contextual Logging and Observability Architecture.

Provides:
- ContextVars-based correlation_id and kiosk_id propagation across async tasks.
- Rotating plain-text log with contextual tags for console and disk (logs/platform.log).
- Rotating machine-readable structured JSONL log (logs/platform.jsonl).
- Thread-safe and async-safe context binding via bind_log_context().
"""

import contextvars
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from typing import Any, Dict, Optional

correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)
kiosk_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "kiosk_id", default="-"
)


def bind_log_context(
    correlation_id: Optional[str] = None,
    kiosk_id: Optional[str] = None,
) -> None:
    """Bind contextual correlation and kiosk IDs into the current task context."""
    if correlation_id is not None:
        correlation_id_ctx.set(correlation_id)
    if kiosk_id is not None:
        kiosk_id_ctx.set(kiosk_id)


def clear_log_context() -> None:
    """Reset context variables to defaults."""
    correlation_id_ctx.set("-")
    kiosk_id_ctx.set("-")


import re

# ── Secret Redaction Filter (SEC-6) ──────────────────────────────────────────

_SENSITIVE_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE),
    re.compile(r"(ak_live_)[a-f0-9]{32,}", re.IGNORECASE),
    re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)[^\"'\s&]{4,}", re.IGNORECASE),
    re.compile(r"(key=)[A-Za-z0-9_\-]{15,}", re.IGNORECASE),
    re.compile(r"(token=)[A-Za-z0-9_\-]{15,}", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    """Scrub sensitive credentials, tokens, and API keys from log strings."""
    if not text:
        return text
    redacted = text
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\1***REDACTED***", redacted)
    return redacted


class SecretRedactingFilter(logging.Filter):
    """Filter that sanitizes credentials, tokens, and passwords from LogRecords."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


class ContextualLogFilter(logging.Filter):
    """Injects correlation_id and kiosk_id into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        setattr(record, "corr_id", correlation_id_ctx.get())
        setattr(record, "kiosk_id", kiosk_id_ctx.get())
        return True


class JsonlFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "corr_id", "-"),
            "kiosk_id": getattr(record, "kiosk_id", "-"),
            "message": redact_secrets(record.getMessage()),
            "file": record.filename,
            "line": record.lineno,
        }
        if record.exc_info:
            data["exception"] = redact_secrets(self.formatException(record.exc_info))
        return json.dumps(data, ensure_ascii=False)


def setup_platform_logging(log_dir_str: str = "logs") -> None:
    """Configure platform-wide root logger with console, text file, and JSONL file handlers."""
    log_dir = Path(log_dir_str)
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ctx_filter = ContextualLogFilter()
    secret_filter = SecretRedactingFilter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [corr:%(corr_id)s] [kiosk:%(kiosk_id)s] [%(name)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(ctx_filter)
    console_handler.addFilter(secret_filter)
    root_logger.addHandler(console_handler)

    text_file_path = log_dir / "platform.log"
    file_handler = RotatingFileHandler(
        str(text_file_path),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(console_formatter)
    file_handler.addFilter(ctx_filter)
    file_handler.addFilter(secret_filter)
    root_logger.addHandler(file_handler)

    jsonl_file_path = log_dir / "platform.jsonl"
    jsonl_handler = RotatingFileHandler(
        str(jsonl_file_path),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    jsonl_handler.setLevel(logging.INFO)
    jsonl_handler.setFormatter(JsonlFormatter())
    jsonl_handler.addFilter(ctx_filter)
    jsonl_handler.addFilter(secret_filter)
    root_logger.addHandler(jsonl_handler)
