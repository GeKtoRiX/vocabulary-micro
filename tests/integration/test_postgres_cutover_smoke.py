import json
import os
import shlex
import signal
import socket
import subprocess
import time
import uuid
import urllib.error
import urllib.request
import re
from contextlib import contextmanager
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DOCKER_SMOKE = os.getenv("RUN_DOCKER_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_DOCKER_SMOKE,
    reason="Set RUN_DOCKER_SMOKE=1 to run Docker/Postgres cutover smoke.",
)


def _run_shell(command: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=True,
    )


def _docker_exec(container_name: str, sql: str) -> str:
    inner_command = " ".join([
        "docker exec",
        shlex.quote(container_name),
        "psql -U postgres -d vocabulary -At -c",
        shlex.quote(sql),
    ])
    command = f"sg docker -c {shlex.quote(inner_command)}"
    return _run_shell(command).stdout.strip()


def _wait_for_postgres(container_name: str, timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            result = _run_shell(
                f"sg docker -c 'docker exec {container_name} pg_isready -U postgres -d vocabulary'",
                timeout=10,
            )
            if "accepting connections" in result.stdout:
                return
        except subprocess.CalledProcessError as error:
            last_error = error.stderr or error.stdout
        time.sleep(1)
    raise AssertionError(f"Postgres did not become ready: {last_error}")


def _allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _request_json_allow_error(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        payload_bytes = error.read()
        payload_text = payload_bytes.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError:
            parsed = {"detail": payload_text}
        return error.code, parsed


def _request_text(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read().decode("utf-8")


def _request_bytes(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, bytes, dict[str, str]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read(), dict(response.headers.items())


def _request_bytes_allow_error(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, bytes, dict[str, str]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers.items())


def _asset_paths_from_html(html: str) -> list[str]:
    return sorted(set(
        match.group(1)
        for match in re.finditer(r"""(?:src|href)=["'](/assets/[^"']+)["']""", html)
    ))


def _wait_for_json(url: str, timeout_seconds: int = 60) -> dict:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            _, payload = _request_json(url)
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            last_error = str(error)
        time.sleep(1)
    raise AssertionError(f"{url} did not become ready: {last_error}")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _cleanup_local_stack_processes() -> None:
    patterns = [
        "[t]sx src/dev.ts",
        "[t]sx src/index.ts",
        "[p]ython3 main_nlp.py",
        "[p]ython3 main_export.py",
        "[p]ython3 main_web.py",
        "[b]ash ./start.sh",
    ]
    for pattern in patterns:
        subprocess.run(
            ["bash", "-lc", f"pkill -f {shlex.quote(pattern)} || true"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )


def _kill_process_by_pattern(pattern: str) -> None:
    subprocess.run(
        ["bash", "-lc", f"pkill -f {shlex.quote(pattern)} || true"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@contextmanager
def _running_host_stack(
    tmp_path: Path,
    *,
    env_overrides: dict[str, str] | None = None,
):
    try:
        _run_shell("sg docker -c 'docker ps'", timeout=20)
    except subprocess.CalledProcessError as error:
        pytest.skip(f"Docker daemon is not available for this process: {error.stderr or error.stdout}")

    container_name = f"vocabulary-cutover-{uuid.uuid4().hex[:8]}"
    postgres_port = _allocate_free_port()
    log_path = tmp_path / f"{container_name}.log"
    process: subprocess.Popen[bytes] | None = None

    try:
        _cleanup_local_stack_processes()
        _run_shell(f"sg docker -c 'docker rm -f {container_name} >/dev/null 2>&1 || true'")
        _run_shell(
            " ".join([
                "sg docker -c",
                f"'docker run -d --name {container_name}",
                "-e POSTGRES_DB=vocabulary",
                "-e POSTGRES_USER=postgres",
                "-e POSTGRES_PASSWORD=postgres",
                f"-p {postgres_port}:5432 postgres:16'",
            ]),
            timeout=120,
        )
        _wait_for_postgres(container_name)

        env = os.environ.copy()
        env.update({
            "START_LEGACY_BACKEND": "0",
            "OWNER_SERVICES_STORAGE_BACKEND": "postgres",
            "OWNER_SERVICES_POSTGRES_URL": f"postgresql://postgres:postgres@127.0.0.1:{postgres_port}/vocabulary",
            "OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE": "1",
        })
        if env_overrides:
            env.update(env_overrides)

        with log_path.open("wb") as log_file:
            process = subprocess.Popen(
                ["bash", "-lc", "./start.sh --postgres"],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

            try:
                system_health = _wait_for_json("http://127.0.0.1:8765/api/system/health")
                lexicon_health = _wait_for_json("http://127.0.0.1:4011/health")
                assignments_health = _wait_for_json("http://127.0.0.1:4012/health")
            except Exception:
                _terminate_process(process)
                logs = log_path.read_text("utf-8", errors="replace")
                raise AssertionError(f"Stack did not start successfully.\n\n{logs}")

        yield {
            "container_name": container_name,
            "postgres_port": postgres_port,
            "log_path": log_path,
            "process": process,
            "system_health": system_health,
            "lexicon_health": lexicon_health,
            "assignments_health": assignments_health,
        }
    finally:
        if process is not None:
            _terminate_process(process)
        _cleanup_local_stack_processes()
        _run_shell(f"sg docker -c 'docker rm -f {container_name} >/dev/null 2>&1 || true'")


def _run_assignment_scan(title: str, term: str) -> tuple[int, str]:
    status, scan_start = _request_json(
        "http://127.0.0.1:8765/api/assignments/scan",
        method="POST",
        payload={
            "title": title,
            "content_original": "I walk in the park.",
            "content_completed": f"I {term} swiftly in the park.",
        },
    )
    assert status == 200
    job_id = scan_start["job_id"]
    status, stream_payload = _request_text(
        f"http://127.0.0.1:8765/api/assignments/scan/jobs/{job_id}/stream",
    )
    assert status == 200
    assert '"type":"result"' in stream_payload
    assert title in stream_payload

    assignments = _request_json("http://127.0.0.1:8765/api/assignments")[1]
    created = next(item for item in assignments if item["title"] == title)
    return int(created["id"]), stream_payload


@pytest.fixture()
def running_postgres_cutover_stack(tmp_path: Path):
    with _running_host_stack(tmp_path) as stack:
        yield stack


def test_postgres_cutover_smoke(running_postgres_cutover_stack: dict[str, object]) -> None:
    container_name = str(running_postgres_cutover_stack["container_name"])
    lexicon_health = running_postgres_cutover_stack["lexicon_health"]
    assignments_health = running_postgres_cutover_stack["assignments_health"]

    assert lexicon_health["storage_backend"] == "postgres"
    assert assignments_health["storage_backend"] == "postgres"

    initial_assignments = _request_json("http://127.0.0.1:8765/api/assignments")[1]
    baseline_assignment_count = len(initial_assignments)

    suffix = uuid.uuid4().hex[:8]
    category_name = f"Postgres Smoke {suffix}"
    term = f"postgresprobe{suffix}"
    title = f"Postgres Assignment Smoke {suffix}"

    status, category_payload = _request_json(
        "http://127.0.0.1:8765/api/lexicon/categories",
        method="POST",
        payload={"name": category_name},
    )
    assert status == 200
    assert category_name in category_payload["categories"]

    status, entry_payload = _request_json(
        "http://127.0.0.1:8765/api/lexicon/entries",
        method="POST",
        payload={
            "category": category_name,
            "value": term,
            "source": "manual",
            "confidence": 0.99,
        },
    )
    assert status == 200
    assert term in entry_payload["message"]

    status, search_payload = _request_json(
        f"http://127.0.0.1:8765/api/lexicon/entries?status=all&limit=20&offset=0&value_filter={term}"
    )
    assert status == 200
    assert any(row["normalized"] == term for row in search_payload["rows"])

    _, stream_payload = _run_assignment_scan(title, term)

    statistics = _request_json("http://127.0.0.1:8765/api/statistics")[1]
    assert statistics["overview"]["total_assignments"] >= baseline_assignment_count + 1

    lexicon_count = _docker_exec(
        container_name,
        f"select count(*) from lexicon.lexicon_entries where normalized = '{term}';",
    )
    assignment_row = _docker_exec(
        container_name,
        f"select title || '|' || status from assignments.assignments where title = '{title}';",
    )
    migration_rows = _docker_exec(
        container_name,
        (
            "select service_name || ':' || version "
            "from service_postgres_migrations "
            "where service_name in ('lexicon-service', 'assignments-service') "
            "order by service_name, version;"
        ),
    ).splitlines()

    assert lexicon_count == "1"
    assert assignment_row == f"{title}|PENDING"
    assert "assignments-service:0001_init" in migration_rows
    assert "lexicon-service:0001_init" in migration_rows
    schema_rows = _docker_exec(
        container_name,
        (
            "select schema_name "
            "from information_schema.schemata "
            "where schema_name in ('lexicon', 'assignments') "
            "order by schema_name;"
        ),
    ).splitlines()
    assert schema_rows == ["assignments", "lexicon"]


def test_bulk_rescan_gateway(running_postgres_cutover_stack: dict[str, object]) -> None:
    baseline_assignment_count = len(_request_json("http://127.0.0.1:8765/api/assignments")[1])
    suffix = uuid.uuid4().hex[:8]
    category_name = f"Bulk Rescan Smoke {suffix}"
    term = f"bulkprobe{suffix}"

    status, _ = _request_json(
        "http://127.0.0.1:8765/api/lexicon/categories",
        method="POST",
        payload={"name": category_name},
    )
    assert status == 200
    status, _ = _request_json(
        "http://127.0.0.1:8765/api/lexicon/entries",
        method="POST",
        payload={
            "category": category_name,
            "value": term,
            "source": "manual",
            "confidence": 0.99,
        },
    )
    assert status == 200

    assignment_ids = []
    for index in range(3):
        assignment_id, _ = _run_assignment_scan(f"Bulk Rescan {suffix}-{index}", term)
        assignment_ids.append(assignment_id)

    status, bulk_start = _request_json(
        "http://127.0.0.1:8765/api/assignments/bulk-rescan",
        method="POST",
        payload={"assignment_ids": assignment_ids},
    )
    assert status == 200
    bulk_job_id = bulk_start["job_id"]

    status, stream_payload = _request_text(
        f"http://127.0.0.1:8765/api/assignments/scan/jobs/{bulk_job_id}/stream",
    )
    assert status == 200
    assert '"type":"result"' in stream_payload
    statistics = _request_json("http://127.0.0.1:8765/api/statistics")[1]
    assert statistics["overview"]["total_assignments"] >= baseline_assignment_count + 3


def test_lexicon_export_returns_xlsx(running_postgres_cutover_stack: dict[str, object]) -> None:
    suffix = uuid.uuid4().hex[:8]
    category_name = f"Export Smoke {suffix}"
    term = f"exportprobe{suffix}"

    status, _ = _request_json(
        "http://127.0.0.1:8765/api/lexicon/categories",
        method="POST",
        payload={"name": category_name},
    )
    assert status == 200
    status, _ = _request_json(
        "http://127.0.0.1:8765/api/lexicon/entries",
        method="POST",
        payload={
            "category": category_name,
            "value": term,
            "source": "manual",
            "confidence": 0.99,
        },
    )
    assert status == 200

    status, body, headers = _request_bytes("http://127.0.0.1:8765/api/lexicon/export")
    assert status == 200
    content_type = headers.get("Content-Type", headers.get("content-type", ""))
    assert content_type.startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(body) > 1024


def test_statistics_composition(running_postgres_cutover_stack: dict[str, object]) -> None:
    suffix = uuid.uuid4().hex[:8]
    category_name = f"Stats Smoke {suffix}"
    term = f"statsprobe{suffix}"

    status, _ = _request_json(
        "http://127.0.0.1:8765/api/lexicon/categories",
        method="POST",
        payload={"name": category_name},
    )
    assert status == 200
    status, _ = _request_json(
        "http://127.0.0.1:8765/api/lexicon/entries",
        method="POST",
        payload={
            "category": category_name,
            "value": term,
            "source": "manual",
            "confidence": 0.99,
        },
    )
    assert status == 200

    _run_assignment_scan(f"Stats Assignment {suffix}", term)

    statistics = _request_json("http://127.0.0.1:8765/api/statistics")[1]
    assert statistics["overview"]["total_assignments"] > 0
    assert 0 <= statistics["overview"]["average_assignment_coverage"] <= 100


def test_frontend_shell_and_assets_are_served(running_postgres_cutover_stack: dict[str, object]) -> None:
    status, html = _request_text("http://127.0.0.1:8765/")
    assert status == 200
    assert '<div id="root"></div>' in html

    asset_paths = _asset_paths_from_html(html)
    assert asset_paths

    for asset_path in asset_paths:
        asset_status, asset_body, _ = _request_bytes(f"http://127.0.0.1:8765{asset_path}")
        assert asset_status == 200
        assert len(asset_body) > 0

    warmup = _request_json("http://127.0.0.1:8765/api/system/warmup")[1]
    assert set(warmup).issuperset({"running", "ready", "failed", "error_message", "elapsed_sec"})


def test_runtime_failure_modes_surface_public_errors(running_postgres_cutover_stack: dict[str, object]) -> None:
    _kill_process_by_pattern("[p]ython3 main_nlp.py")
    time.sleep(1)

    status, parse_start = _request_json(
        "http://127.0.0.1:8765/api/parse",
        method="POST",
        payload={"text": "I run quickly."},
    )
    assert status == 200
    status, parse_stream = _request_text(
        f"http://127.0.0.1:8765/api/parse/jobs/{parse_start['job_id']}/stream",
    )
    assert status == 200
    assert '"type":"error"' in parse_stream

    _kill_process_by_pattern("[p]ython3 main_export.py")
    time.sleep(1)

    status, export_payload = _request_json_allow_error("http://127.0.0.1:8765/api/lexicon/export")
    assert status == 502
    assert str(export_payload.get("detail", "")).strip()


def test_gateway_legacy_rollbacks_host_run(tmp_path: Path) -> None:
    with _running_host_stack(tmp_path, env_overrides={
        "START_LEGACY_BACKEND": "1",
        "GATEWAY_PARSE_BACKEND": "legacy",
        "GATEWAY_LEXICON_BACKEND": "legacy",
        "GATEWAY_ASSIGNMENTS_BACKEND": "legacy",
        "GATEWAY_STATISTICS_BACKEND": "legacy",
        "GATEWAY_EXPORT_BACKEND": "legacy",
    }):
        warmup = _request_json("http://127.0.0.1:8765/api/system/warmup")[1]
        assert set(warmup).issuperset({"running", "ready", "failed", "error_message", "elapsed_sec"})

        lexicon = _request_json(
            "http://127.0.0.1:8765/api/lexicon/entries?status=all&limit=20&offset=0"
        )[1]
        assert "rows" in lexicon

        assignments = _request_json("http://127.0.0.1:8765/api/assignments")[1]
        assert isinstance(assignments, list)

        statistics = _request_json("http://127.0.0.1:8765/api/statistics")[1]
        assert "overview" in statistics

        status, body, headers = _request_bytes_allow_error("http://127.0.0.1:8765/api/lexicon/export")
        assert status == 200, body.decode("utf-8", errors="replace")
        content_type = headers.get("Content-Type", headers.get("content-type", ""))
        assert content_type.startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert len(body) > 1024
