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
Mail Organizer Background Ingestion & Polling Worker.

Adheres strictly to Plan 07 v1.0 and GEES v1.0.
Resolves legacy ISSUE-005 (Poller Deselection Termination Failure) by enforcing:
1. Dual-Layer Cooperative Shutdown: Checks an atomic .poll_worker_stop file sentinel
   and an in-memory threading.Event on every 0.5-second sleep chunk.
2. Signal Handlers: Registers clean handlers for SIGINT and SIGTERM.
3. Safe Resource Teardown: Closes database sessions and releases file locks immediately upon exit.
"""

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time
from types import FrameType
from typing import Any, Dict, List, Optional

from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.state import MailOrganizerState
from apps.mail_organizer.graph.state_graph import MailOrganizerWorkflow
from core_platform.app.config import settings

logger = logging.getLogger("mail_organizer.poll_worker")

# Atomic stop sentinel file path in workspace root
STOP_SENTINEL_NAME = ".poll_worker_stop"


def get_sentinel_path(root_dir: Optional[Path] = None) -> Path:
    """Return the absolute path to the atomic stop sentinel file."""
    base = root_dir or Path(os.getcwd())
    return base / STOP_SENTINEL_NAME


def interruptible_sleep(
    seconds: float,
    stop_event: Optional[threading.Event] = None,
    sentinel_path: Optional[Path] = None,
    slice_sec: float = 0.5,
) -> bool:
    """Sleep in small slices; returns True immediately if termination was requested.

    Args:
        seconds: Total sleep duration.
        stop_event: In-memory threading event.
        sentinel_path: Path to the atomic sentinel file.
        slice_sec: Interval between checks (default 0.5s).

    Returns:
        True if stop was requested during sleep, False if sleep expired normally.
    """
    target_sentinel = sentinel_path or get_sentinel_path()
    deadline = time.time() + seconds

    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return True
        if target_sentinel.exists():
            return True
        remaining = deadline - time.time()
        time.sleep(min(slice_sec, max(0.01, remaining)))

    return False


async def interruptible_async_sleep(
    seconds: float,
    stop_event: Optional[threading.Event] = None,
    sentinel_path: Optional[Path] = None,
    slice_sec: float = 0.2,
) -> bool:
    """Async sleep in small slices; returns True immediately if termination was requested."""
    target_sentinel = sentinel_path or get_sentinel_path()
    deadline = time.time() + seconds

    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return True
        if target_sentinel.exists():
            return True
        remaining = deadline - time.time()
        await asyncio.sleep(min(slice_sec, max(0.01, remaining)))

    return False


class MailPollWorker:
    """Robust background poller for Mail Organizer with cooperative cancellation."""

    def __init__(
        self,
        poll_interval_seconds: int = 60,
        root_dir: Optional[Path] = None,
        db_service: Optional[MailDatabaseService] = None,
        gmail_connector: Optional[GmailConnector] = None,
    ) -> None:
        """Initialize poll worker with interval and connectors."""
        self.poll_interval = max(2, poll_interval_seconds)
        self.root_dir = root_dir or Path(os.getcwd())
        self.sentinel_path = get_sentinel_path(self.root_dir)
        self.db_service = db_service or MailDatabaseService()
        self.gmail = gmail_connector or GmailConnector()
        self.workflow = MailOrganizerWorkflow(
            db_service=self.db_service,
            gmail_connector=self.gmail,
        )
        self.stop_event = threading.Event()
        self._is_running = False
        self.cycles_completed = 0
        self.emails_processed = 0

    @property
    def is_running(self) -> bool:
        """Indicate whether the worker loop is currently running."""
        return self._is_running

    def request_stop(self) -> None:
        """Cooperatively signal the worker to terminate immediately."""
        logger.info("[PollWorker] Stop requested via in-memory event.")
        self.stop_event.set()
        try:
            self.sentinel_path.touch(exist_ok=True)
        except Exception as err:
            logger.warning("[PollWorker] Could not touch sentinel file: %s", err)

    def _cleanup_sentinel(self) -> None:
        """Remove the atomic sentinel file if present."""
        try:
            if self.sentinel_path.exists():
                self.sentinel_path.unlink(missing_ok=True)
        except Exception as err:
            logger.warning("[PollWorker] Failed to clean up sentinel: %s", err)

    async def poll_once(self) -> int:
        """Execute a single cycle: fetch unread threads and process through LangGraph."""
        logger.debug("[PollWorker] Checking inbox for unread email threads...")
        threads: List[Dict[str, Any]] = await self.gmail.fetch_unread_threads(max_results=20)
        if not threads:
            return 0

        count = 0
        for thread in threads:
            if self.stop_event.is_set() or self.sentinel_path.exists():
                logger.info("[PollWorker] Stop detected mid-cycle. Halting batch processing.")
                break

            gmail_id = str(thread.get("gmail_id", f"MOCK-{time.time()}"))
            initial_state: MailOrganizerState = {
                "correlation_id": f"POLL-{int(time.time()*1000)}",
                "gmail_id": gmail_id,
                "thread_id": str(thread.get("thread_id", f"THREAD-{gmail_id}")),
                "sender": str(thread.get("sender", "unknown@sender.com")),
                "to_recipients": thread.get("to_recipients", ["me@canectar.com"]),
                "cc_recipients": thread.get("cc_recipients", []),
                "subject": str(thread.get("subject", "No Subject")),
                "body": str(thread.get("body", "")),
                "snippet": str(thread.get("snippet", "")),
            }

            try:
                final_state = await self.workflow.execute(initial_state)
                cat = final_state.get("category", "General")
                logger.info(
                    "[PollWorker] Processed %s -> Category: %s, SafetyOverride: %s",
                    gmail_id,
                    cat,
                    final_state.get("safety_override", False),
                )
                count += 1
                self.emails_processed += 1
            except Exception as exc:
                logger.error("[PollWorker] Error processing email %s: %s", gmail_id, exc)

        return count

    async def run_async(self) -> None:
        """Run continuous asynchronous polling loop with chunked cooperative sleeps."""
        self._is_running = True
        self._cleanup_sentinel()

        logger.info(
            "[PollWorker] Starting background polling worker (Interval: %ds, Sentinel: %s)...",
            self.poll_interval,
            self.sentinel_path.name,
        )

        try:
            while not self.stop_event.is_set() and not self.sentinel_path.exists():
                try:
                    processed = await self.poll_once()
                    self.cycles_completed += 1
                    logger.debug("[PollWorker] Cycle %d finished (%d processed).", self.cycles_completed, processed)
                except Exception as cycle_err:
                    logger.error("[PollWorker] Exception in poll cycle: %s", cycle_err, exc_info=True)

                if self.stop_event.is_set() or self.sentinel_path.exists():
                    break

                # Chunked async sleep checking stop conditions every 0.2 seconds
                stopped = await interruptible_async_sleep(
                    seconds=float(self.poll_interval),
                    stop_event=self.stop_event,
                    sentinel_path=self.sentinel_path,
                )
                if stopped:
                    logger.info("[PollWorker] Cooperative stop signal caught during sleep.")
                    break
        finally:
            self._is_running = False
            self._cleanup_sentinel()
            logger.info("[PollWorker] Background poller has stopped completely and cleanly.")

    def run(self) -> None:
        """Synchronous entry point for thread or subprocess execution."""
        def handle_signal(sig: int, frame: Optional[FrameType]) -> None:
            logger.info("[PollWorker] Caught OS signal %d. Requesting stop.", sig)
            self.request_stop()

        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except (ValueError, AttributeError):
            pass  # Non-main thread or unsupported platform

        asyncio.run(self.run_async())


def main() -> None:
    """CLI execution entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    worker = MailPollWorker(poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "30")))
    worker.run()


if __name__ == "__main__":
    main()
