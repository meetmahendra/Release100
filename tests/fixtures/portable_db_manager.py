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
Portable Standalone Database Cluster Manager for Local Testing (GEES v2.0).

Manages 100% self-contained, real physical database server daemons in `D:\\Release100\\.databases\\`:
1. SQLite (WAL Mode & In-Memory)
2. DuckDB (Embedded Columnar Analytical Engine)
3. PostgreSQL 16 (Real Physical Server Process on port 54329 with full query logging to pgsql.log)
4. MariaDB 10.11 / MySQL (Real Physical Server Process on port 33069 with query logging to mariadb.log & mariadb_queries.log)
5. TimescaleDB (PostgreSQL dialect telemetry)
6. MSSQL (Informative driver / dialect compilation verification)
"""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, Optional
import uuid


class PortableDatabaseManager:
    """Manages lifecycle, daemons, and storage paths of portable test databases under .databases/."""

    _instance: Optional["PortableDatabaseManager"] = None

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "PortableDatabaseManager":
        if cls._instance is None:
            cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        if root_dir is None:
            root_dir = Path(__file__).resolve().parent.parent.parent / ".databases"
        self.root_dir = root_dir
        self.sqlite_dir = self.root_dir / "sqlite"
        self.duckdb_dir = self.root_dir / "duckdb"
        self.pgsql_dir = self.root_dir / "pgsql"
        self.mariadb_dir = self.root_dir / "mariadb"
        self.logs_dir = self.root_dir / "logs"
        self.downloads_dir = self.root_dir / "downloads"

        self._ensure_directories()
        self._active_processes: Dict[str, Any] = {}

    def _ensure_directories(self) -> None:
        """Create isolated folder tree under .databases/."""
        for d in [self.sqlite_dir, self.duckdb_dir, self.pgsql_dir, self.mariadb_dir, self.logs_dir, self.downloads_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _is_port_open(self, port: int, host: str = "127.0.0.1") -> bool:
        """Check if TCP port is currently accepting connections."""
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except Exception:
            return False

    # ── PostgreSQL Lifecycle Management ─────────────────────────────────────

    def start_postgres(self, port: int = 54329) -> str:
        """Start isolated portable PostgreSQL daemon on specified port with full query logging."""
        if self._is_port_open(port):
            return f"postgresql://postgres@127.0.0.1:{port}/postgres"

        bin_dir = self.pgsql_dir / "bin"
        data_dir = self.pgsql_dir / "data"
        log_file = self.logs_dir / "pgsql.log"
        initdb_exe = bin_dir / "initdb.exe"
        pg_ctl_exe = bin_dir / "pg_ctl.exe"

        if not initdb_exe.exists():
            raise FileNotFoundError(f"Portable PostgreSQL binary not found at {initdb_exe}")

        if not data_dir.exists():
            subprocess.run(
                [
                    str(initdb_exe),
                    "-D", str(data_dir),
                    "-U", "postgres",
                    "-A", "trust",
                    "-E", "UTF8",
                    "--no-locale",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

        cmd = [
            str(pg_ctl_exe),
            "-D", str(data_dir),
            "-l", str(log_file),
            "-o", f"-p {port} -c listen_addresses=127.0.0.1 -c log_destination=stderr -c log_statement=all -c log_duration=on",
            "start",
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # Wait up to 10 seconds for PostgreSQL to accept connections
        for _ in range(30):
            if self._is_port_open(port):
                break
            time.sleep(0.3)

        return f"postgresql://postgres@127.0.0.1:{port}/postgres"

    def stop_postgres(self) -> None:
        """Gracefully stop portable PostgreSQL daemon."""
        pg_ctl_exe = self.pgsql_dir / "bin" / "pg_ctl.exe"
        data_dir = self.pgsql_dir / "data"
        if pg_ctl_exe.exists() and data_dir.exists():
            try:
                subprocess.run(
                    [str(pg_ctl_exe), "-D", str(data_dir), "-m", "fast", "stop"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

    # ── MariaDB / MySQL Lifecycle Management ────────────────────────────────

    def start_mariadb(self, port: int = 33069) -> str:
        """Start isolated portable MariaDB daemon on specified port with full query and error logging."""
        if self._is_port_open(port):
            return f"mysql+pymysql://root:@127.0.0.1:{port}/platform_test"

        bin_dir = self.mariadb_dir / "bin"
        data_dir = self.mariadb_dir / "data"
        log_file = self.logs_dir / "mariadb.log"
        query_log_file = self.logs_dir / "mariadb_queries.log"
        install_db_exe = bin_dir / "mariadb-install-db.exe"
        mysqld_exe = bin_dir / "mysqld.exe"

        if not mysqld_exe.exists():
            raise FileNotFoundError(f"Portable MariaDB binary not found at {mysqld_exe}")

        if not data_dir.exists():
            subprocess.run(
                [
                    str(install_db_exe),
                    f"--datadir={data_dir}",
                    "--default-user=root",
                    f"--port={port}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

        proc = subprocess.Popen(
            [
                str(mysqld_exe),
                f"--datadir={data_dir}",
                f"--port={port}",
                "--bind-address=127.0.0.1",
                f"--log-error={log_file}",
                "--general-log=1",
                f"--general-log-file={query_log_file}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._active_processes["mariadb"] = proc

        # Wait up to 10 seconds for MariaDB to accept connections
        for _ in range(30):
            if self._is_port_open(port):
                break
            time.sleep(0.3)

        # Ensure platform_test database exists
        try:
            import pymysql  # type: ignore[import-untyped]
            conn = pymysql.connect(host="127.0.0.1", port=port, user="root", password="")
            cur = conn.cursor()
            cur.execute("CREATE DATABASE IF NOT EXISTS platform_test;")
            conn.commit()
            conn.close()
        except Exception:
            pass

        return f"mysql+pymysql://root:@127.0.0.1:{port}/platform_test"

    def stop_mariadb(self) -> None:
        """Gracefully stop portable MariaDB daemon."""
        mysqladmin_exe = self.mariadb_dir / "bin" / "mysqladmin.exe"
        if mysqladmin_exe.exists():
            try:
                subprocess.run(
                    [str(mysqladmin_exe), "-u", "root", "-P", "33069", "-h", "127.0.0.1", "shutdown"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass
        proc = self._active_processes.pop("mariadb", None)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # ── Universal URL Resolvers ─────────────────────────────────────────────

    def get_sqlite_url(self, db_name: Optional[str] = None) -> str:
        """Return file path URL for real disk-backed SQLite with WAL mode."""
        name = db_name or f"test_{uuid.uuid4().hex[:8]}.db"
        db_path = self.sqlite_dir / name
        if db_path.exists():
            try:
                db_path.unlink()
            except Exception:
                pass
        return f"sqlite:///{db_path}"

    def get_duckdb_url(self, db_name: Optional[str] = None) -> str:
        """Return file path URL for real in-process DuckDB columnar database."""
        name = db_name or f"analytics_{uuid.uuid4().hex[:8]}.duckdb"
        db_path = self.duckdb_dir / name
        if db_path.exists():
            try:
                db_path.unlink()
            except Exception:
                pass
        return f"duckdb:///{db_path}"

    def get_postgresql_url(self) -> str:
        """Return live portable PostgreSQL connection URL."""
        return self.start_postgres(port=54329)

    def get_mysql_url(self) -> str:
        """Return live portable MariaDB / MySQL connection URL."""
        return self.start_mariadb(port=33069)

    def get_timescaledb_url(self) -> str:
        """Return TimescaleDB URL (backed by live PostgreSQL instance)."""
        return self.get_postgresql_url()

    def get_mssql_url(self) -> str:
        """Return MSSQL connection URL for dialect and schema compilation."""
        return os.environ.get(
            "TEST_MSSQL_URL",
            "mssql+pyodbc://sa:Password123!@127.0.0.1:1433/platform_test?driver=ODBC+Driver+17+for+SQL+Server",
        )

    def wipe_all_data(self) -> None:
        """Completely delete and purge .databases/ directory."""
        self.shutdown_all()
        if self.root_dir.exists():
            shutil.rmtree(self.root_dir, ignore_errors=True)

    def shutdown_all(self) -> None:
        """Gracefully stop all active portable database daemons."""
        self.stop_postgres()
        self.stop_mariadb()
        for name, proc in list(self._active_processes.items()):
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._active_processes.clear()


def get_portable_db_manager() -> PortableDatabaseManager:
    return PortableDatabaseManager.get_instance()
