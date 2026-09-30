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

"""Platform Outbox -- offline-first edge resilience queue service."""
from core_platform.app.outbox.queue import PlatformOutboxQueue, get_platform_outbox
from core_platform.app.outbox.redis_outbox import RedisOutboxSynchronizer, StreamMessage
from core_platform.app.outbox.synchronizer import OutboxSynchronizer
from core_platform.app.outbox.worker_pool import OutboxWorkerPool

__all__ = [
    "PlatformOutboxQueue",
    "get_platform_outbox",
    "OutboxSynchronizer",
    "RedisOutboxSynchronizer",
    "StreamMessage",
    "OutboxWorkerPool",
]

