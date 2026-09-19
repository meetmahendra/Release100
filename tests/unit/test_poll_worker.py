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

"""Synthetic Unit Tests for MailPollWorker & MailPollerManager (Resolving ISSUE-005)."""

import os
from pathlib import Path
import threading
import time
import pytest

from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.services.poll_worker import (
    MailPollWorker,
    get_sentinel_path,
    interruptible_sleep,
)
from apps.mail_organizer.services.poller_manager import MailPollerManager


def test_interruptible_sleep_sentinel_trigger(tmp_path: Path) -> None:
    """Sleep must terminate immediately when sentinel file is created."""
    sentinel = tmp_path / ".poll_worker_stop"
    stop_event = threading.Event()

    def touch_after_delay() -> None:
        time.sleep(0.1)
        sentinel.touch()

    threading.Thread(target=touch_after_delay, daemon=True).start()

    t0 = time.time()
    interrupted = interruptible_sleep(seconds=5.0, stop_event=stop_event, sentinel_path=sentinel, slice_sec=0.05)
    elapsed = time.time() - t0

    assert interrupted is True
    assert elapsed < 1.0  # Must break well before 5.0 seconds


def test_interruptible_sleep_event_trigger(tmp_path: Path) -> None:
    """Sleep must terminate immediately when threading.Event is set."""
    sentinel = tmp_path / ".poll_worker_stop"
    stop_event = threading.Event()

    def set_event_after_delay() -> None:
        time.sleep(0.1)
        stop_event.set()

    threading.Thread(target=set_event_after_delay, daemon=True).start()

    t0 = time.time()
    interrupted = interruptible_sleep(seconds=5.0, stop_event=stop_event, sentinel_path=sentinel, slice_sec=0.05)
    elapsed = time.time() - t0

    assert interrupted is True
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_mail_poll_worker_poll_once(tmp_path: Path) -> None:
    """PollWorker must fetch mock unread emails and process them through the workflow."""
    db_file = tmp_path / "test_poller.db"
    db_service = MailDatabaseService(db_url=f"sqlite:///{db_file}")
    gmail = GmailConnector(mock_mode=True)
    gmail.seed_mock_thread(
        gmail_id="TEST-POLL-01",
        thread_id="THREAD-POLL-01",
        subject="Urgent: Refrigeration Valve Breakdown",
        sender="maintenance@factory.internal",
        body="Immediate replacement needed on chiller #02 compressor valve.",
    )

    worker = MailPollWorker(
        poll_interval_seconds=2,
        root_dir=tmp_path,
        db_service=db_service,
        gmail_connector=gmail,
    )

    count = await worker.poll_once()
    assert count == 1
    assert worker.emails_processed == 1


def test_mail_poller_manager_lifecycle(tmp_path: Path) -> None:
    """PollerManager must start, report running, and stop cleanly with zero zombies."""
    manager = MailPollerManager(root_dir=tmp_path)
    assert manager.is_running() is False

    started = manager.start(poll_interval_seconds=1)
    assert started is True
    assert manager.is_running() is True

    status = manager.get_status()
    assert status["is_running"] is True
    assert status["status"] == "RUNNING"

    # Stop poller
    stopped = manager.stop(timeout=2.0)
    assert stopped is True
    assert manager.is_running() is False

    status_after = manager.get_status()
    assert status_after["is_running"] is False
    assert status_after["status"] == "STOPPED"


def test_interruptible_sleep_normal_expiry(tmp_path: Path) -> None:
    """Sleep must expire normally when no stop is requested."""
    sentinel = tmp_path / ".poll_worker_stop"
    stop_event = threading.Event()

    interrupted = interruptible_sleep(seconds=0.1, stop_event=stop_event, sentinel_path=sentinel, slice_sec=0.05)
    assert interrupted is False


@pytest.mark.asyncio
async def test_mail_poll_worker_run_async_stop(tmp_path: Path) -> None:
    """run_async must exit gracefully when stop_event is triggered."""
    worker = MailPollWorker(poll_interval_seconds=1, root_dir=tmp_path)
    worker.stop_event.set()  # Pre-set stop

    await worker.run_async()
    assert worker.is_running is False

