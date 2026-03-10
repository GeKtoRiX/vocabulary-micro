import json
import os
import shlex
import signal
import subprocess
import time
import uuid
import urllib.error
import urllib.request
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


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


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
        "node /home/cbandy/vocabulary-main/services/node_modules/.bin/tsx src/index.ts",
        "python3 main_nlp.py",
        "python3 main_export.py",
        "bash ./start.sh",
    ]
    for pattern in patterns:
        subprocess.run(
            ["bash", "-lc", f"pkill -f {shlex.quote(pattern)} || true"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )


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
    try:
        _run_shell("sg docker -c 'docker ps'", timeout=20)
    except subprocess.CalledProcessError as error:
        pytest.skip(f"Docker daemon is not available for this process: {error.stderr or error.stdout}")

    container_name = f"vocabulary-cutover-{uuid.uuid4().hex[:8]}"
    postgres_port = 55432
    log_path = tmp_path / "postgres-cutover.log"
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
            "system_health": system_health,
            "lexicon_health": lexicon_health,
            "assignments_health": assignments_health,
        }
    finally:
        if process is not None:
            _terminate_process(process)
        _cleanup_local_stack_processes()
        _run_shell(f"sg docker -c 'docker rm -f {container_name} >/dev/null 2>&1 || true'")


def test_postgres_cutover_smoke(running_postgres_cutover_stack: dict[str, object]) -> None:
    container_name = str(running_postgres_cutover_stack["container_name"])
    lexicon_health = running_postgres_cutover_stack["lexicon_health"]
    assignments_health = running_postgres_cutover_stack["assignments_health"]

    assert lexicon_health["storage_backend"] == "postgres"
    assert assignments_health["storage_backend"] == "postgres"

    initial_assignments = _request_json("http://127.0.0.1:8765/api/assignments")[1]
    assert len(initial_assignments) >= 2

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
    assert statistics["overview"]["total_assignments"] >= 3

    lexicon_count = _docker_exec(
        container_name,
        f"select count(*) from lexicon_entries where normalized = '{term}';",
    )
    assignment_row = _docker_exec(
        container_name,
        f"select title || '|' || status from assignments where title = '{title}';",
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


def test_bulk_rescan_gateway(running_postgres_cutover_stack: dict[str, object]) -> None:
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
    assert statistics["overview"]["total_assignments"] >= 5


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
