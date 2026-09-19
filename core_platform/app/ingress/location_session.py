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
Thread-Safe Ephemeral Location Session Cache.

Bridges 1-click mobile HTML5 geolocation link submissions (`/loc?session=wa-xxx`)
to inbound WhatsApp interactions and Layer 0 Location verification nodes.
"""

import threading
import time
from typing import Any, Dict, Optional, Tuple


class LocationSessionCache:
    """Thread-safe in-memory cache for correlation session coordinates with TTL."""

    _instance: Optional["LocationSessionCache"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "LocationSessionCache":
        """Get singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        """Initialize session cache."""
        self._cache: Dict[str, Tuple[Tuple[float, float], float]] = {}
        self._metadata: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self._lock = threading.Lock()

    def bind_metadata(
        self,
        session_id: str,
        metadata: Dict[str, Any],
        ttl_seconds: int = 1800,
    ) -> None:
        """Associate metadata (e.g. sender_phone, kiosk_id) with a session ID."""
        if not session_id:
            return
        expire_at = time.time() + ttl_seconds
        with self._lock:
            self._metadata[session_id.strip()] = (metadata, expire_at)

    def get_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve active metadata for a session ID if not expired."""
        if not session_id:
            return None
        key = session_id.strip()
        with self._lock:
            entry = self._metadata.get(key)
            if not entry:
                return None
            meta, expire_at = entry
            if time.time() > expire_at:
                del self._metadata[key]
                return None
            return meta

    def get_phone(self, session_id: str) -> Optional[str]:
        """Convenience method to look up sender phone for a session ID."""
        meta = self.get_metadata(session_id)
        if meta and "phone" in meta:
            return str(meta["phone"])
        return None

    def set_coordinates(
        self,
        session_id: str,
        coords: Tuple[float, float],
        ttl_seconds: int = 1800,
    ) -> None:
        """Cache verified coordinates for a session with expiration timestamp.

        Args:
            session_id: Correlation or phone session identifier.
            coords: (latitude, longitude) tuple.
            ttl_seconds: Time to live in seconds (default 30 minutes).
        """
        if not session_id:
            return
        expire_at = time.time() + ttl_seconds
        with self._lock:
            self._cache[session_id.strip()] = (coords, expire_at)

    def get_coordinates(self, session_id: str) -> Optional[Tuple[float, float]]:
        """Retrieve coordinates if session exists and is not expired.

        Args:
            session_id: Session identifier.

        Returns:
            (latitude, longitude) tuple if valid, else None.
        """
        if not session_id:
            return None
        key = session_id.strip()
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            coords, expire_at = entry
            if time.time() > expire_at:
                del self._cache[key]
                return None
            return coords

    def clear(self, session_id: str) -> None:
        """Remove a session from cache."""
        with self._lock:
            self._cache.pop(session_id.strip(), None)
            self._metadata.pop(session_id.strip(), None)


# Global convenience helpers
def bind_session_metadata(session_id: str, metadata: Dict[str, Any], ttl_seconds: int = 1800) -> None:
    """Associate metadata (e.g. sender_phone) with a session identifier."""
    LocationSessionCache.get_instance().bind_metadata(session_id, metadata, ttl_seconds)


def get_session_metadata(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve session metadata dictionary."""
    return LocationSessionCache.get_instance().get_metadata(session_id)


def get_session_phone(session_id: str) -> Optional[str]:
    """Retrieve phone number associated with a session identifier."""
    return LocationSessionCache.get_instance().get_phone(session_id)
def set_session_coordinates(session_id: str, coords: Tuple[float, float], ttl_seconds: int = 600) -> None:
    """Store GPS coordinates in correlation session cache."""
    LocationSessionCache.get_instance().set_coordinates(session_id, coords, ttl_seconds)


def get_session_coordinates(session_id: str) -> Optional[Tuple[float, float]]:
    """Retrieve cached GPS coordinates for a correlation session."""
    return LocationSessionCache.get_instance().get_coordinates(session_id)
