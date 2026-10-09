#!/usr/bin/env python3
"""Start or stop the Longaeva demo without Docker.

Requires Python 3.12+ and Node.js 20.19+. Downloads PostgreSQL 16 into var/
when nothing is already accepting the demo database on port 55432.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).resolve().parent / "postgres-binaries.json"
BACKEND = PACKAGE_ROOT / "backend"
FRONTEND = PACKAGE_ROOT / "frontend"
VAR = PACKAGE_ROOT / "var"
PG_HOME = VAR / "postgres" / "server"
PG_DATA = VAR / "postgres" / "data"
PG_SOCKET = VAR / "postgres" / "socket"
RUN_DIR = VAR / "run"
LOG_DIR = VAR / "log"
VENV = BACKEND / ".venv"
REQUIREMENTS_STAMP = VENV / ".requirements-stamp"

DB_HOST = "127.0.0.1"
DB_PORT = 55432
API_PORT = 8000
WEB_PORT = 3000
DATABASE_URL = "postgresql://longaeva:longaeva@127.0.0.1:55432/longaeva"
ADMIN_DATABASE_URL = "postgresql://longaeva@127.0.0.1:55432/postgres"
MIN_PYTHON = (3, 12)
MIN_NODE = (20, 19, 0)
STOP_HINT = "Stop the other stack with `make down` or `make down-local`, then retry."


class SetupError(Exception):
    """A startup or shutdown problem the user can act on."""


def format_version(version: tuple[int, ...]) -> str:
    parts = list(version[:3])
    while len(parts) < 3:
        parts.append(0)
    return ".".join(str(part) for part in parts)


def python_version_error(version: tuple[int, ...]) -> str | None:
    if version >= MIN_PYTHON:
        return None
    return f"Python 3.12 or newer is required. Found Python {format_version(version)}."


def parse_node_version(text: str) -> tuple[int, int, int]:
    raw = text.strip()
    if raw.startswith(("v", "V")):
        raw = raw[1:]
    raw = raw.split("-", 1)[0].split("+", 1)[0]
    parts = raw.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:3]):
        raise SetupError(f"Could not read the Node.js version from {text.strip()!r}.")
    numbers = [int(part) for part in parts[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


def node_version_error(version: tuple[int, int, int]) -> str | None:
    if version >= MIN_NODE:
        return None
    found = ".".join(str(part) for part in version)
    return f"Node.js 20.19.0 or newer is required. Found Node.js {found}."


def platform_key(system: str, machine: str, *, musl: bool = False) -> str:
    """Return the Postgres binary manifest key for this machine."""
    system_name = system.lower()
    machine_name = machine.lower()
    if system_name == "linux" and musl:
        raise SetupError("Alpine and other musl systems are not supported. Use make up with Docker.")
    if system_name == "darwin" and machine_name in {"arm64", "aarch64"}:
        return "darwin-arm64v8"
    if system_name == "darwin" and machine_name in {"x86_64", "amd64"}:
        return "darwin-amd64"
    if system_name == "linux" and machine_name in {"x86_64", "amd64"}:
        return "linux-amd64"
    if system_name == "linux" and machine_name in {"aarch64", "arm64"}:
        return "linux-arm64v8"
    if system_name == "windows" and machine_name in {"arm64", "aarch64"}:
        raise SetupError("Windows on ARM is not supported. Use make up with Docker.")
    if system_name == "windows" and machine_name in {"amd64", "x86_64"}:
        return "windows-amd64"
    raise SetupError(f"{system} {machine} is not supported for the no-Docker startup. Use make up with Docker.")


def load_manifest(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SetupError(f"Postgres manifest {path} is not an object.")
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual.lower() != expected.lower():
        path.unlink(missing_ok=True)
        raise SetupError(f"Postgres download checksum did not match. Expected {expected}, got {actual}.")


def linux_is_musl() -> bool:
    if platform.system() != "Linux":
        return False
    if Path("/etc/alpine-release").is_file():
        return True
    try:
        proc = subprocess.run(["ldd", "--version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    return "musl" in f"{proc.stdout}\n{proc.stderr}".lower()


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def pg_executable(name: str) -> Path:
    suffix = ".exe" if platform.system() == "Windows" else ""
    return PG_HOME / "bin" / f"{name}{suffix}"


def binaries_ready() -> bool:
    return all(pg_executable(name).is_file() for name in ("initdb", "pg_ctl", "postgres"))


def postgres_env() -> dict[str, str]:
    env = os.environ.copy()
    lib = str(PG_HOME / "lib")
    bin_dir = str(PG_HOME / "bin")
    if platform.system() == "Windows":
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    else:
        env["LD_LIBRARY_PATH"] = lib + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        env["DYLD_LIBRARY_PATH"] = lib + os.pathsep + env.get("DYLD_LIBRARY_PATH", "")
    return env


def app_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    env["ARTIFACT_DIR"] = str(VAR / "artifacts")
    env["WORKER_HEARTBEAT_PATH"] = str(RUN_DIR / "worker-heartbeat")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd, env=env, check=False)
    if result.returncode != 0:
        rendered = " ".join(cmd)
        raise SetupError(f"Command failed ({result.returncode}): {rendered}")


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((DB_HOST, port)) == 0


def pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_pid(name: str) -> int | None:
    path = RUN_DIR / name
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


PID_TOKENS = {
    "api.pid": "longaeva_app.api.main:app",
    "worker.pid": "longaeva_app.worker.loop",
    "web.pid": "run dev",
}


def process_command(pid: int) -> str:
    proc_path = Path(f"/proc/{pid}/cmdline")
    if proc_path.is_file():
        return proc_path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
    if platform.system() == "Windows":
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout
    proc = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False)
    return proc.stdout


def owned_process_running(pid_name: str) -> bool:
    pid = read_pid(pid_name)
    if pid is None or not pid_alive(pid):
        return False
    return PID_TOKENS[pid_name] in process_command(pid)


def listener_hint(port: int) -> str:
    try:
        if platform.system() == "Windows":
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                check=False,
            )
            needle = f":{port}"
            lines = [line.strip() for line in proc.stdout.splitlines() if needle in line and "LISTEN" in line.upper()]
            return "\n".join(lines)
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return ""
    return proc.stdout.strip()


def port_conflict(port: int, label: str) -> SetupError:
    hint = listener_hint(port)
    detail = f"\n{hint}" if hint else ""
    return SetupError(f"Port {port} is already in use ({label}). {STOP_HINT}{detail}")


def require_node() -> None:
    if shutil.which("node") is None or shutil.which("npm") is None:
        raise SetupError("Node.js 20.19.0 or newer is required, and node or npm was not found on PATH.")
    try:
        out = subprocess.check_output(["node", "--version"], text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SetupError("Node.js 20.19.0 or newer is required, and `node --version` failed.") from exc
    error = node_version_error(parse_node_version(out))
    if error:
        raise SetupError(error)


def requirements_digest() -> str:
    digest = hashlib.sha256()
    for name in ("requirements.txt", "requirements.lock"):
        digest.update((BACKEND / name).read_bytes())
    return digest.hexdigest()


def ensure_venv() -> None:
    python = venv_python()
    if not python.is_file():
        print("Creating the Python environment...", flush=True)
        run([sys.executable, "-m", "venv", str(VENV)])
    digest = requirements_digest()
    if REQUIREMENTS_STAMP.is_file() and REQUIREMENTS_STAMP.read_text(encoding="utf-8").strip() == digest:
        return
    print("Installing Python packages...", flush=True)
    run([str(venv_python()), "-m", "pip", "install", "-r", "requirements.txt", "-c", "requirements.lock"], cwd=BACKEND)
    REQUIREMENTS_STAMP.write_text(digest + "\n", encoding="utf-8")


def ensure_node_modules() -> None:
    if (FRONTEND / "node_modules").is_dir():
        return
    npm = shutil.which("npm")
    if npm is None:
        raise SetupError("npm was not found on PATH.")
    print("Installing web dependencies...", flush=True)
    run([npm, "ci"], cwd=FRONTEND)


def manifest_entry() -> tuple[str, dict[str, str]]:
    manifest = load_manifest(MANIFEST_PATH)
    version = manifest.get("version")
    platforms = manifest.get("platforms")
    if not isinstance(version, str) or not isinstance(platforms, dict):
        raise SetupError(f"Postgres manifest {MANIFEST_PATH} is missing version or platforms.")
    key = platform_key(platform.system(), platform.machine(), musl=linux_is_musl())
    entry = platforms.get(key)
    if not isinstance(entry, dict) or not isinstance(entry.get("url"), str) or not isinstance(entry.get("sha256"), str):
        raise SetupError(f"Postgres manifest has no download for {key}.")
    return version, {"url": entry["url"], "sha256": entry["sha256"]}


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "longaeva-up-local"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        partial.replace(dest)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise SetupError(f"Could not download PostgreSQL from {url}: {exc}") from exc


def extract_postgres(jar: Path) -> None:
    if PG_HOME.exists():
        shutil.rmtree(PG_HOME)
    PG_HOME.mkdir(parents=True)
    download_dir = VAR / "postgres" / "download"
    download_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar) as archive:
        names = [name for name in archive.namelist() if name.endswith(".txz")]
        if len(names) != 1:
            raise SetupError("Postgres archive did not contain a single .txz payload.")
        txz = download_dir / Path(names[0]).name
        with archive.open(names[0]) as source, txz.open("wb") as handle:
            shutil.copyfileobj(source, handle)
    try:
        with tarfile.open(txz, "r:xz") as archive:
            archive.extractall(PG_HOME, filter="data")
    finally:
        txz.unlink(missing_ok=True)
    if platform.system() != "Windows":
        for path in (PG_HOME / "bin").iterdir():
            if path.is_file():
                path.chmod(path.stat().st_mode | 0o755)


def ensure_binaries() -> None:
    if binaries_ready():
        return
    version, entry = manifest_entry()
    print(f"Downloading PostgreSQL {version}...", flush=True)
    jar = VAR / "postgres" / "download" / "postgres.jar"
    try:
        download(entry["url"], jar)
        verify_sha256(jar, entry["sha256"])
        extract_postgres(jar)
    except Exception:
        if PG_HOME.exists() and not binaries_ready():
            shutil.rmtree(PG_HOME, ignore_errors=True)
        raise
    finally:
        jar.unlink(missing_ok=True)
    if not binaries_ready():
        raise SetupError("Postgres binaries were downloaded but initdb was not found.")


def configure_cluster() -> None:
    conf = PG_DATA / "postgresql.conf"
    text = conf.read_text(encoding="utf-8")
    marker = "# longaeva up-local"
    head = text.split(marker)[0].rstrip()
    lines = [
        "",
        marker,
        "listen_addresses = '127.0.0.1'",
        f"port = {DB_PORT}",
    ]
    if platform.system() != "Windows":
        PG_SOCKET.mkdir(parents=True, exist_ok=True)
        escaped = str(PG_SOCKET).replace("'", "''")
        lines.append(f"unix_socket_directories = '{escaped}'")
    conf.write_text(head + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def private_postgres_running() -> bool:
    pg_ctl = pg_executable("pg_ctl")
    if not pg_ctl.is_file() or not (PG_DATA / "PG_VERSION").is_file():
        return False
    proc = subprocess.run(
        [str(pg_ctl), "-D", str(PG_DATA), "status"],
        capture_output=True,
        text=True,
        check=False,
        env=postgres_env(),
    )
    return proc.returncode == 0


def _psycopg(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(venv_python()), "-c", script, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def database_accepts() -> bool:
    probe = "import sys\nimport psycopg\npsycopg.connect(sys.argv[1], connect_timeout=3).close()\n"
    return _psycopg(probe, DATABASE_URL).returncode == 0


def ensure_demo_database() -> bool:
    """Create the demo database. initdb creates the role, not this database."""
    script = """
import sys
import psycopg
from psycopg import sql
admin_url, db_name = sys.argv[1], sys.argv[2]
with psycopg.connect(admin_url, connect_timeout=3, autocommit=True) as conn:
    exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)).fetchone()
    if exists is None:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
"""
    return _psycopg(script, ADMIN_DATABASE_URL, "longaeva").returncode == 0


def wait_for_database() -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        if ensure_demo_database() and database_accepts():
            return
        time.sleep(0.4)
    raise SetupError(f"PostgreSQL started but rejected the demo login. See {LOG_DIR / 'postgres.log'}.")


def ensure_database() -> None:
    if port_open(DB_PORT):
        if ensure_demo_database() and database_accepts():
            print(f"Using PostgreSQL on {DB_HOST}:{DB_PORT}.", flush=True)
            return
        raise port_conflict(DB_PORT, "database login failed")
    print("Starting PostgreSQL...", flush=True)
    ensure_binaries()
    if not (PG_DATA / "PG_VERSION").is_file():
        PG_DATA.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                str(pg_executable("initdb")),
                "-D",
                str(PG_DATA),
                "-U",
                "longaeva",
                "--locale=C",
                "--encoding=UTF8",
                "--auth=trust",
            ],
            env=postgres_env(),
        )
    configure_cluster()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ctl = [
        str(pg_executable("pg_ctl")),
        "-D",
        str(PG_DATA),
        "-l",
        str(LOG_DIR / "postgres.log"),
        "-w",
    ]
    if private_postgres_running():
        ctl.extend(["-m", "fast", "restart"])
    else:
        ctl.append("start")
    run(ctl, env=postgres_env())
    wait_for_database()


def spawn(cmd: list[str], *, cwd: Path, env: dict[str, str], log_name: str, pid_name: str) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = (LOG_DIR / log_name).open("ab")
    kwargs: dict[str, object] = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log_handle, stderr=subprocess.STDOUT, **kwargs)
    finally:
        log_handle.close()
    (RUN_DIR / pid_name).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def assert_app_ports_available() -> None:
    checks = ((API_PORT, "api.pid", "API"), (WEB_PORT, "web.pid", "web app"))
    for port, pid_name, label in checks:
        if port_open(port) and not owned_process_running(pid_name):
            raise port_conflict(port, label)


def start_logged_service(
    *,
    port: int | None,
    pid_name: str,
    label: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    log_name: str,
) -> int:
    running = owned_process_running(pid_name)
    listening = port is not None and port_open(port)
    if listening and not running:
        raise port_conflict(port, label)
    if running and (port is None or listening):
        pid = read_pid(pid_name)
        if pid is None:
            raise SetupError(f"The {label} process id disappeared.")
        return pid
    if running:
        stop_pidfile(pid_name)
    return spawn(cmd, cwd=cwd, env=env, log_name=log_name, pid_name=pid_name)


def wait_http(url: str, log_name: str, timeout: float) -> None:
    deadline = time.time() + timeout
    last = "no response"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
                last = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            if 200 <= exc.code < 500:
                return
            last = f"HTTP {exc.code}"
        except Exception as exc:
            last = str(exc)
        time.sleep(0.4)
    raise SetupError(f"Timed out waiting for {url} ({last}). See {LOG_DIR / log_name}.")


def wait_for_worker(pid: int) -> None:
    path = RUN_DIR / "worker-heartbeat"
    deadline = time.time() + 30
    while time.time() < deadline:
        if not pid_alive(pid):
            raise SetupError(f"The worker exited. See {LOG_DIR / 'worker.log'}.")
        if path.is_file():
            return
        time.sleep(0.2)
    raise SetupError(f"The worker did not become ready. See {LOG_DIR / 'worker.log'}.")


def migrate_and_seed() -> None:
    (VAR / "artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading the demo database...", flush=True)
    python = str(venv_python())
    run([python, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=app_env())
    run([python, "-m", "longaeva_app.cli", "seed-demo"], cwd=BACKEND, env=app_env())


def start_services() -> None:
    print("Starting the API, worker, and web app...", flush=True)
    python = str(venv_python())
    start_logged_service(
        port=API_PORT,
        pid_name="api.pid",
        label="API",
        cmd=[python, "-m", "uvicorn", "longaeva_app.api.main:app", "--host", DB_HOST, "--port", str(API_PORT)],
        cwd=BACKEND,
        env=app_env(),
        log_name="api.log",
    )
    worker_pid = start_logged_service(
        port=None,
        pid_name="worker.pid",
        label="worker",
        cmd=[python, "-m", "longaeva_app.worker.loop"],
        cwd=BACKEND,
        env=app_env(),
        log_name="worker.log",
    )
    npm = shutil.which("npm")
    if npm is None:
        raise SetupError("npm was not found on PATH.")
    start_logged_service(
        port=WEB_PORT,
        pid_name="web.pid",
        label="web app",
        cmd=[npm, "run", "dev", "--", "--host", DB_HOST, "--port", str(WEB_PORT)],
        cwd=FRONTEND,
        env=os.environ.copy(),
        log_name="web.log",
    )
    wait_http(f"http://{DB_HOST}:{API_PORT}/health", "api.log", 90)
    wait_for_worker(worker_pid)
    wait_http(f"http://{DB_HOST}:{WEB_PORT}/", "web.log", 90)


def bring_up() -> None:
    version_error = python_version_error(tuple(sys.version_info))
    if version_error:
        raise SetupError(version_error)
    require_node()
    assert_app_ports_available()
    ensure_venv()
    ensure_node_modules()
    ensure_database()
    migrate_and_seed()
    start_services()
    print("Longaeva is running.", flush=True)
    print(f"Web app: http://{DB_HOST}:{WEB_PORT}", flush=True)
    print(f"API health: http://{DB_HOST}:{API_PORT}/health", flush=True)
    print("Stop with make down-local, or on Windows: .\\scripts\\up-local.ps1 -Down", flush=True)


def stop_pidfile(name: str) -> None:
    pid = read_pid(name)
    command = process_command(pid) if pid is not None and pid_alive(pid) else ""
    (RUN_DIR / name).unlink(missing_ok=True)
    if pid is None or not pid_alive(pid) or PID_TOKENS[name] not in command:
        return
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline and pid_alive(pid):
        time.sleep(0.1)
    if pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except PermissionError:
            os.kill(pid, signal.SIGKILL)


def stop_private_postgres() -> None:
    pg_ctl = pg_executable("pg_ctl")
    if not pg_ctl.is_file() or not (PG_DATA / "PG_VERSION").is_file():
        return
    if not private_postgres_running():
        return
    subprocess.run(
        [str(pg_ctl), "-D", str(PG_DATA), "-m", "fast", "stop"],
        capture_output=True,
        text=True,
        check=False,
        env=postgres_env(),
    )


def stop_all() -> None:
    for name in ("web.pid", "api.pid", "worker.pid"):
        stop_pidfile(name)
    stop_private_postgres()
    print("Longaeva local processes are stopped.")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Longaeva without Docker.")
    parser.add_argument("--down", action="store_true", help="Stop the processes started by this command.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        version_error = python_version_error(tuple(sys.version_info))
        if version_error:
            raise SetupError(version_error)
        if args.down:
            stop_all()
        else:
            bring_up()
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
