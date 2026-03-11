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

PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
        "[p]ython3 -m backend.python_services.nlp_service.main",
        "[p]ython3 -m backend.python_services.export_service.main",
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
            "OWNER_SERVICES_POSTGRES_URL": f"postgresql://postgres:postgres@127.0.0.1:{postgres_port}/vocabulary",
            "BERT_DEVICE": "cpu",
        })
        if env_overrides:
            env.update(env_overrides)

        with log_path.open("wb") as log_file:
            process = subprocess.Popen(
                ["bash", "-lc", "./start.sh"],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

            try:
                system_health = _wait_for_json("http://127.0.0.1:8765/api/system/health")
                lexicon_health = _wait_for_json("http://127.0.0.1:4011/health")
                assignments_health = _wait_for_json("http://127.0.0.1:4012/health")
                nlp_health = _wait_for_json("http://127.0.0.1:8767/internal/v1/system/health")
                export_health = _wait_for_json("http://127.0.0.1:8768/internal/v1/system/health")
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
            "nlp_health": nlp_health,
            "export_health": export_health,
        }
    finally:
        if process is not None:
            _terminate_process(process)
        _cleanup_local_stack_processes()
        _run_shell(f"sg docker -c 'docker rm -f {container_name} >/dev/null 2>&1 || true'")


def _create_unit(subunit_contents: list[str]) -> dict:
    status, payload = _request_json(
        "http://127.0.0.1:8765/api/assignments",
        method="POST",
        payload={
            "subunits": [{"content": content} for content in subunit_contents],
        },
    )
    assert status in (200, 201)
    return payload


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
    first_subunit = f"I {term} swiftly in the park."
    second_subunit = f"We repeat {term} again in this unit."

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

    created_unit = _create_unit([first_subunit, second_subunit])

    statistics = _request_json("http://127.0.0.1:8765/api/statistics")[1]
    assert statistics["overview"]["total_units"] >= baseline_assignment_count + 1
    assert statistics["overview"]["total_subunits"] >= 2

    lexicon_count = _docker_exec(
        container_name,
        f"select count(*) from lexicon.lexicon_entries where normalized = '{term}';",
    )
    unit_row = _docker_exec(
        container_name,
        (
            "select unit_code || '|' || subunit_count "
            "from assignments.units "
            f"where id = {int(created_unit['id'])};"
        ),
    )
    subunit_rows = _docker_exec(
        container_name,
        (
            "select subunit_code || '|' || content "
            "from assignments.unit_subunits "
            f"where unit_id = {int(created_unit['id'])} "
            "order by position;"
        ),
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
    assert unit_row == f"{created_unit['unit_code']}|2"
    assert subunit_rows.splitlines() == [
        f"{created_unit['subunits'][0]['subunit_code']}|{first_subunit}",
        f"{created_unit['subunits'][1]['subunit_code']}|{second_subunit}",
    ]
    assert "assignments-service:0001_init" in migration_rows
    assert "assignments-service:0002_units_model" in migration_rows
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
        unit = _create_unit([f"Bulk {term} block {index}A", f"Bulk {term} block {index}B"])
        assignment_ids.append(int(unit["id"]))

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
    assert '"failed_count":3' in stream_payload
    statistics = _request_json("http://127.0.0.1:8765/api/statistics")[1]
    assert statistics["overview"]["total_units"] >= baseline_assignment_count + 3


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

    _create_unit([f"Stats {term} block A", f"Stats {term} block B", f"Stats {term} block C"])

    statistics = _request_json("http://127.0.0.1:8765/api/statistics")[1]
    assert statistics["overview"]["total_units"] > 0
    assert statistics["overview"]["total_subunits"] > 0
    assert statistics["overview"]["average_subunits_per_unit"] >= 1


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
    _kill_process_by_pattern("[p]ython3 -m backend.python_services.nlp_service.main")
    time.sleep(1)

    try:
        status, parse_start = _request_json(
            "http://127.0.0.1:8765/api/parse",
            method="POST",
            payload={"text": "I run quickly."},
        )
    except urllib.error.URLError as error:
        assert "Connection refused" in str(error)
        return

    assert status == 200
    status, parse_stream = _request_text(
        f"http://127.0.0.1:8765/api/parse/jobs/{parse_start['job_id']}/stream",
    )
    assert status == 200
    assert '"type":"error"' in parse_stream
