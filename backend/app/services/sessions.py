import asyncio, time, secrets
from dataclasses import dataclass, field


@dataclass
class Session:
    id: str
    filename: str
    content: bytes
    content_type: str
    created_at: float = field(default_factory=time.monotonic)
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    result: dict | None = None
    running: bool = False
    task: asyncio.Task | None = None


class SessionStore:
    """Process-local volatile store. Never serializes uploaded content to disk."""
    def __init__(self, ttl: int):
        self._items: dict[str, Session] = {}
        self._ttl = ttl
        self._lock = asyncio.Lock()

    async def create(self, filename: str, content: bytes, content_type: str) -> Session:
        async with self._lock:
            self._expire()
            sid = secrets.token_urlsafe(24)
            item = Session(sid, filename, content, content_type)
            self._items[sid] = item
            return item

    async def get(self, sid: str) -> Session | None:
        async with self._lock:
            self._expire()
            return self._items.get(sid)

    async def purge(self, sid: str) -> bool:
        async with self._lock:
            item = self._items.pop(sid, None)
            if item:
                if item.task and not item.task.done():
                    item.task.cancel()
                item.content = b""
                item.result = None
                while not item.events.empty():
                    item.events.get_nowait()
            return item is not None

    def _expire(self):
        now = time.monotonic()
        for sid, item in list(self._items.items()):
            if now - item.created_at > self._ttl:
                if item.task and not item.task.done():
                    item.task.cancel()
                item.content = b""
                item.result = None
                while not item.events.empty():
                    item.events.get_nowait()
                self._items.pop(sid, None)

