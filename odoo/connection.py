"""Connection management utilities for interacting with Odoo via odoorpc."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Lock
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import odoorpc
from odoorpc.error import RPCError

from config.settings import OdooSettings, get_odoo_settings

Domain = Sequence[Any]
Fields = Sequence[str]
ReadGroupFields = Sequence[str]


class OdooIntegrationError(RuntimeError):
    """Raised when the application fails to communicate with Odoo."""


@dataclass
class _PooledConnection:
    client: odoorpc.ODOO
    created_at: float
    last_used: float


class OdooConnectionManager:
    """Thread-safe connection manager with lightweight pooling."""

    def __init__(self, settings: Optional[OdooSettings] = None):
        self.settings = settings or get_odoo_settings()
        self._pool: "Queue[_PooledConnection]" = Queue(maxsize=self.settings.pool_max_connections)
        self._lock = Lock()
        self._total_connections = 0
        self._warmed = False

    def _warm_pool(self) -> None:
        if self._warmed:
            return
        with self._lock:
            if self._warmed:
                return
            target = min(self.settings.pool_min_connections, self.settings.pool_max_connections)
            for _ in range(target):
                wrapper = self._create_connection()
                self._pool.put(wrapper)
                self._total_connections += 1
            self._warmed = True

    def _create_connection(self) -> _PooledConnection:
        if not self.settings.api_key:
            raise OdooIntegrationError("Missing Odoo API key. Set ODOO_API_KEY in the environment.")

        try:
            client = odoorpc.ODOO(
                self.settings.host,
                protocol=self.settings.protocol,
                port=self.settings.port,
                version=self.settings.version,
            )
            client.login(self.settings.database, self.settings.username, self.settings.api_key)
        except Exception as exc:  # pragma: no cover - network interaction
            raise OdooIntegrationError("Failed to establish connection to Odoo.") from exc

        now = time.time()
        return _PooledConnection(client=client, created_at=now, last_used=now)

    def _close_connection(self, wrapper: _PooledConnection) -> None:
        try:
            wrapper.client.logout()
        except Exception:
            pass
        finally:
            with self._lock:
                self._total_connections = max(0, self._total_connections - 1)

    def _should_discard(self, wrapper: _PooledConnection) -> bool:
        now = time.time()
        max_idle = self.settings.pool_max_idle_time
        max_lifetime = self.settings.pool_max_lifetime
        if max_idle and now - wrapper.last_used > max_idle:
            return True
        if max_lifetime and now - wrapper.created_at > max_lifetime:
            return True
        return False

    def _acquire_connection(self) -> _PooledConnection:
        self._warm_pool()
        deadline = time.time() + self.settings.pool_connection_timeout

        while True:
            try:
                wrapper = self._pool.get_nowait()
            except Empty:
                wrapper = self._maybe_create_connection()
                if wrapper is not None:
                    return wrapper

                remaining = deadline - time.time()
                if remaining <= 0:
                    raise OdooIntegrationError("Timed out waiting for an available Odoo connection.")
                try:
                    wrapper = self._pool.get(timeout=remaining)
                except Empty:
                    raise OdooIntegrationError("No Odoo connections available.")

            if self._should_discard(wrapper):
                self._close_connection(wrapper)
                continue

            return wrapper

    def _maybe_create_connection(self) -> Optional[_PooledConnection]:
        with self._lock:
            if self._total_connections >= self.settings.pool_max_connections:
                return None
            wrapper = self._create_connection()
            self._total_connections += 1
            return wrapper

    def _release_connection(self, wrapper: _PooledConnection) -> None:
        wrapper.last_used = time.time()
        try:
            self._pool.put_nowait(wrapper)
        except Full:
            self._close_connection(wrapper)

    @contextmanager
    def connection(self) -> Iterable[odoorpc.ODOO]:
        wrapper = self._acquire_connection()
        try:
            yield wrapper.client
        except RPCError as exc:
            self._close_connection(wrapper)
            raise OdooIntegrationError("Odoo RPC error.") from exc
        except Exception:
            self._close_connection(wrapper)
            raise
        else:
            self._release_connection(wrapper)

    def _execute(self, callback: Callable[[odoorpc.ODOO], Any]) -> Any:
        with self.connection() as client:
            return callback(client)

    def search_read(
        self,
        model_name: str,
        domain: Optional[Domain] = None,
        fields: Optional[Fields] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        domain = domain or []
        fields = fields or []

        def _worker(client: odoorpc.ODOO) -> List[Dict[str, Any]]:
            model = client.env[model_name]
            return model.search_read(
                domain=domain,
                fields=fields,
                limit=limit,
                offset=offset,
                order=order,
            )

        return self._execute(_worker)

    def search_count(self, model_name: str, domain: Optional[Domain] = None) -> int:
        domain = domain or []

        def _worker(client: odoorpc.ODOO) -> int:
            model = client.env[model_name]
            return model.search_count(domain)

        return self._execute(_worker)

    def read_group(
        self,
        model_name: str,
        domain: Optional[Domain],
        fields: ReadGroupFields,
        groupby: Sequence[str],
        limit: Optional[int] = None,
        orderby: Optional[str] = None,
        lazy: bool = True,
    ) -> List[Dict[str, Any]]:
        domain = domain or []

        def _worker(client: odoorpc.ODOO) -> List[Dict[str, Any]]:
            model = client.env[model_name]
            return model.read_group(
                domain,
                list(fields),
                list(groupby),
                limit=limit,
                orderby=orderby,
                lazy=lazy,
            )

        return self._execute(_worker)

    def ping(self) -> bool:
        try:
            self._execute(lambda client: client.db.list())
            return True
        except OdooIntegrationError:
            return False


connection_manager = OdooConnectionManager()
