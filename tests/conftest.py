"""Shared pytest fixtures."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from taskboard8_api.main import app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class PostgresServer:
    """A throwaway Postgres server in its own data directory."""

    def __init__(self, base_dir: Path) -> None:
        initdb = shutil.which("initdb")
        pg_ctl = shutil.which("pg_ctl")
        if initdb is None or pg_ctl is None:
            pytest.exit(
                "Postgres binaries not found: run the tests through `devbox run test`",
                returncode=2,
            )
        assert initdb is not None
        assert pg_ctl is not None
        self._pg_ctl = pg_ctl
        self._dir = base_dir / "pgdata"
        self.port = _free_port()
        subprocess.run(
            [initdb, "-D", str(self._dir), "-U", "postgres", "-A", "trust", "-E", "UTF8"]
            + ["--no-sync"],
            check=True,
            capture_output=True,
        )

    @property
    def url(self) -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/postgres"

    def start(self) -> None:
        options = (
            f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories='' "
            "-c fsync=off -c synchronous_commit=off -c full_page_writes=off"
        )
        subprocess.run(
            [self._pg_ctl, "-D", str(self._dir), "-l", str(self._dir / "log")]
            + ["-w", "-o", options, "start"],
            check=True,
            capture_output=True,
        )
        deadline = time.monotonic() + 30
        while True:
            try:
                psycopg.connect(self.url, connect_timeout=2).close()
                return
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)

    def stop(self) -> None:
        subprocess.run(
            [self._pg_ctl, "-D", str(self._dir), "-m", "fast", "-w", "stop"],
            check=False,
            capture_output=True,
        )


@pytest.fixture(scope="session", autouse=True)
def postgres_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start one throwaway Postgres for the session and point DATABASE_URL at it."""
    server = PostgresServer(tmp_path_factory.mktemp("postgres"))
    server.start()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = server.url
    try:
        yield server.url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        server.stop()


@pytest.fixture(autouse=True)
def _empty_tasks_table(postgres_url: str) -> None:
    """Start every test from an empty tasks table (never drops it)."""
    with psycopg.connect(postgres_url, autocommit=True) as conn:
        row = conn.execute("SELECT to_regclass('public.tasks')").fetchone()
        if row is not None and row[0] is not None:
            conn.execute("TRUNCATE tasks")


@pytest.fixture()
def restartable_postgres(tmp_path: Path) -> Iterator[PostgresServer]:
    """A second server that a test can stop and start on the same data and port."""
    server = PostgresServer(tmp_path)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def refused_database_url() -> str:
    """A URL on a local port where nothing listens."""
    return f"postgresql://postgres@127.0.0.1:{_free_port()}/postgres"


@pytest.fixture()
def blackhole_database_url() -> Iterator[str]:
    """A URL for a local listener that accepts connections and never answers."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    held: list[socket.socket] = []
    stop = threading.Event()

    def _accept() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            held.append(conn)

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    try:
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in held:
            conn.close()
        listener.close()


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)
