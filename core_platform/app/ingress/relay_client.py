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
Outbound Cloud Relay WebSocket Client (`relay_client.py`).

Adheres strictly to Plan 01 Section 1.3 and Plan 05 Section 4.
Solves the enterprise factory firewall / NAT / port-forwarding challenge:
1. Dials outbound from the local kiosk to the Cloudflare Worker / Render relay:
   `wss://<relay_domain>/ws/{kiosk_id}`
2. Listens for incoming WhatsApp webhook payload frames streamed over WebSocket.
3. Automatically reconnects with exponential backoff on network dropouts or edge hibernation.
4. Dispatches frames into the internal multi-application ingress router.
"""

import asyncio
import concurrent.futures.thread  # Pre-initialize threadpool atexit handler
from datetime import datetime, timezone
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from core_platform.app.config import settings

logger = logging.getLogger("core_platform.relay_client")


class CloudRelayClient:
    """Resilient outbound WebSocket client bridging local kiosks to cloud relays."""

    _instance: Optional["CloudRelayClient"] = None

    @classmethod
    def get_instance(cls) -> "CloudRelayClient":
        """Retrieve the active singleton instance or create a new one."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(
        self,
        relay_url: Optional[str] = None,
        kiosk_id: Optional[str] = None,
        message_handler: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        """Initialize relay client with connection target and message callback."""
        CloudRelayClient._instance = self
        self.kiosk_id = kiosk_id or settings.KIOSK_ID
        raw_url = relay_url if relay_url is not None else settings.RELAY_WS_URL
        self.relay_url = self._format_relay_url(raw_url, self.kiosk_id)
        self.message_handler = message_handler
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self.is_connected = False
        self.last_connected_at: Optional[datetime] = None
        self.messages_received = 0
        self.connection_attempts = 0

    @staticmethod
    def _format_relay_url(url: str, kiosk_id: str) -> str:
        """Ensure WebSocket URL includes the per-kiosk dynamic routing suffix.

        Handles:
        - Cloudflare Worker base URLs: https://my-relay.workers.dev -> wss://my-relay.workers.dev/ws/{kiosk_id}
        - Explicit wss URLs: wss://my-relay.workers.dev/ws/CANEBOT-PUNE-04
        - Template strings: wss://my-relay.workers.dev/ws/{kiosk_id}
        """
        if not url:
            return ""
        trimmed = url.strip().strip('"').strip("'").strip()
        # Convert http(s) -> ws(s)
        if trimmed.startswith("https://"):
            trimmed = "wss://" + trimmed[len("https://") :]
        elif trimmed.startswith("http://"):
            trimmed = "ws://" + trimmed[len("http://") :]

        if "{kiosk_id}" in trimmed:
            return trimmed.replace("{kiosk_id}", kiosk_id)

        # If already points to a specific /ws/:kioskId, keep it
        if "/ws/" in trimmed:
            parts = trimmed.split("/ws/")
            if parts[1].strip():
                return trimmed
            return parts[0] + "/ws/" + kiosk_id

        if trimmed.endswith("/ws") or trimmed.endswith("/ws/"):
            return trimmed.rstrip("/") + "/" + kiosk_id

        # Otherwise, user entered base URL (e.g. wss://release100-relay.xyz.workers.dev)
        return trimmed.rstrip("/") + "/ws/" + kiosk_id

    def start(self) -> Optional[asyncio.Task[None]]:
        """Start the background connection loop if a valid relay URL is configured."""
        if not self.relay_url:
            logger.info("Cloud Relay is disabled (RELAY_WS_URL not set). Running in local/simulator mode.")
            return None

        if self._running:
            logger.warning("Cloud Relay client is already running.")
            return self._task

        self._running = True
        self._task = asyncio.create_task(self._connection_loop(), name="cloud_relay_listener")
        logger.info("Cloud Relay client started targeting %s", self.relay_url)
        return self._task

    async def stop(self) -> None:
        """Signal client shutdown and await loop termination."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.is_connected = False
        logger.info("Cloud Relay client stopped.")

    async def reconfigure_and_restart(
        self, relay_url: Optional[str] = None, kiosk_id: Optional[str] = None
    ) -> None:
        """Dynamically reconfigure relay target and reconnect without restarting application."""
        await self.stop()
        self.kiosk_id = kiosk_id or settings.KIOSK_ID
        raw_url = relay_url if relay_url is not None else settings.RELAY_WS_URL
        self.relay_url = self._format_relay_url(raw_url, self.kiosk_id)
        self.connection_attempts = 0
        if self.relay_url:
            self.start()
            logger.info("[CloudRelay] Dynamically reconfigured and started targeting %s", self.relay_url)
        else:
            logger.info("[CloudRelay] Dynamically reconfigured to empty; client stopped.")

    @property
    def is_running(self) -> bool:
        """Indicate whether the relay client connection loop is actively running."""
        return self._running

    async def _connection_loop(self) -> None:
        """Continuous reconnection loop with exponential backoff."""
        base_delay = max(1, settings.RELAY_RECONNECT_INTERVAL_SECONDS)
        delay = base_delay
        max_delay = 60

        try:
            while True:
                self.connection_attempts += 1
                try:
                    logger.info("Connecting to Cloud Relay: %s (attempt #%d)", self.relay_url, self.connection_attempts)
                    async with websockets.connect(
                        self.relay_url,
                        ping_interval=20,
                        ping_timeout=15,
                        close_timeout=5,
                    ) as ws:
                        self.is_connected = True
                        self.last_connected_at = datetime.now(timezone.utc)
                        delay = base_delay  # reset backoff on successful connection
                        logger.info("Connected to Cloud Relay successfully. Ready for incoming WhatsApp frames.")

                        async for message in ws:
                            self.messages_received += 1
                            await self._handle_raw_message(message)

                except ConnectionClosed as exc:
                    self.is_connected = False
                    logger.warning("Cloud Relay connection closed (%s). Reconnecting in %ds...", exc, delay)
                except Exception as err:
                    self.is_connected = False
                    if "after shutdown" in str(err) or not self._running:
                        logger.info("Cloud Relay terminating gracefully during shutdown.")
                        break
                    logger.error("Cloud Relay connection error: %s. Retrying in %ds...", err, delay)

                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
        except asyncio.CancelledError:
            self.is_connected = False
            logger.info("Cloud Relay connection loop cancelled cleanly.")

    async def _handle_raw_message(self, raw_data: Any) -> None:
        """Parse incoming WebSocket text/binary frame and dispatch to handler."""
        try:
            if isinstance(raw_data, bytes):
                text = raw_data.decode("utf-8")
            else:
                text = str(raw_data)

            payload: Dict[str, Any] = json.loads(text)
            event_type = payload.get("event", "unknown")
            from core_platform.app.telemetry.logging_config import bind_log_context
            bind_log_context(kiosk_id=self.kiosk_id)
            logger.info(
                "[CloudRelay] Received frame: event=%s, size=%d bytes, keys=%s",
                event_type,
                len(text),
                list(payload.keys()),
            )

            if self.message_handler:
                await self.message_handler(payload)
            else:
                # Default handler: feed into internal webhook router
                from core_platform.app.ingress.whatsapp_router import dispatch_whatsapp_payload
                await dispatch_whatsapp_payload(payload)

        except json.JSONDecodeError:
            logger.warning("Received invalid non-JSON payload from Cloud Relay: %s", raw_data[:100] if raw_data else "")
        except Exception as err:
            logger.error("Error processing Cloud Relay payload: %s", err, exc_info=True)
