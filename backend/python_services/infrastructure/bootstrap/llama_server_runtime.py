from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import IO
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from infrastructure.config import PipelineSettings
from infrastructure.logging import AppLoggingService


@dataclass(frozen=True)
class LlamaServerLaunchConfig:
    base_url: str
    executable_path: Path
    model_path: Path
    startup_timeout_ms: int
    n_gpu_layers: int
    ctx_size: int
    threads: int
    batch_size: int
    ubatch_size: int
    alias: str
    rocm_library_dir: Path | None
    parallel_slots: int
    flash_attn: str
    cache_reuse: int
    disable_warmup: bool
    disable_webui: bool
    threads_batch: int
    threads_http: int
    extra_args: tuple[str, ...]


class LlamaCppServerManager:
    def __init__(
        self,
        *,
        settings: PipelineSettings,
        project_root: Path,
        logger: AppLoggingService,
    ) -> None:
        self._settings = settings
        self._project_root = project_root
        self._logger = logger
        self._process: subprocess.Popen[str] | None = None
        self._process_log_handle: IO[str] | None = None

    def is_server_alive(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def ensure_started(self) -> None:
        if not self._settings.enable_third_pass_llm:
            return
        if not self._settings.llama_server_autostart_enabled:
            return

        base_url = str(self._settings.third_pass_llm_base_url or "").strip()
        if not base_url:
            self._logger.warning(
                "llama_server_autostart_disabled: THIRD_PASS_LLM_BASE_URL is empty"
            )
            return
        process = self._process
        if process is not None and process.poll() is not None:
            self._logger.warning(
                "llama_server_autostart_restart: "
                f"managed process exited with code={process.returncode}"
            )
            self.close()
        if self._is_endpoint_ready(base_url=base_url, timeout_seconds=1.0):
            self._logger.info(
                f"llama_server_autostart_skipped: endpoint already ready at {base_url}"
            )
            return
        if self.is_server_alive():
            self._logger.warning(
                "llama_server_autostart_restart: "
                "managed process alive but endpoint is not ready; restarting"
            )
            self.close()

        config = self._build_launch_config(base_url=base_url)
        if config is None:
            return

        self._start_process(config=config)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            self._logger.info("llama_server_autostart_stopped")
        if self._process_log_handle is not None:
            try:
                self._process_log_handle.close()
            except Exception:
                pass
            self._process_log_handle = None

    def _build_launch_config(self, *, base_url: str) -> LlamaServerLaunchConfig | None:
        executable_value = str(self._settings.llama_server_executable or "").strip()
        if not executable_value:
            self._logger.warning(
                "llama_server_autostart_disabled: LLAMA_SERVER_EXECUTABLE is empty"
            )
            return None
        executable_path = Path(executable_value)
        if not executable_path.is_absolute():
            executable_path = self._project_root / executable_path
        executable_path = executable_path.resolve()
        if not executable_path.exists():
            self._logger.warning(
                "llama_server_autostart_disabled: executable not found "
                f"path={executable_path}"
            )
            return None

        model_value = str(self._settings.llama_server_model_path or "").strip()
        if not model_value:
            self._logger.warning(
                "llama_server_autostart_disabled: LLAMA_SERVER_MODEL_PATH is empty"
            )
            return None
        model_path = Path(model_value)
        if not model_path.is_absolute():
            model_path = self._project_root / model_path
        model_path = model_path.resolve()
        if not model_path.exists():
            self._logger.warning(
                "llama_server_autostart_disabled: model not found "
                f"path={model_path}"
            )
            return None

        rocm_library_dir: Path | None = None
        rocm_library_value = str(self._settings.llama_server_rocm_library_dir or "").strip()
        if rocm_library_value:
            candidate = Path(rocm_library_value)
            if not candidate.is_absolute():
                candidate = self._project_root / candidate
            candidate = candidate.resolve()
            if candidate.exists():
                rocm_library_dir = candidate
            else:
                self._logger.warning(
                    "llama_server_rocm_library_dir_missing: "
                    f"path={candidate}; using process PATH only"
                )

        extra_args = self._split_extra_args(str(self._settings.llama_server_extra_args or ""))
        alias = str(self._settings.third_pass_llm_model or "").strip()
        flash_attn = str(self._settings.llama_server_flash_attn or "on").strip().lower()
        if flash_attn not in {"on", "off", "auto"}:
            flash_attn = "on"
        return LlamaServerLaunchConfig(
            base_url=base_url,
            executable_path=executable_path,
            model_path=model_path,
            startup_timeout_ms=max(5_000, int(self._settings.llama_server_startup_timeout_ms)),
            n_gpu_layers=int(self._settings.llama_server_n_gpu_layers),
            ctx_size=max(256, int(self._settings.llama_server_ctx_size)),
            threads=max(0, int(self._settings.llama_server_threads)),
            batch_size=max(64, int(self._settings.llama_server_batch_size)),
            ubatch_size=max(64, int(self._settings.llama_server_ubatch_size)),
            alias=alias,
            rocm_library_dir=rocm_library_dir,
            parallel_slots=max(1, int(self._settings.llama_server_parallel_slots)),
            flash_attn=flash_attn,
            cache_reuse=max(0, int(self._settings.llama_server_cache_reuse)),
            disable_warmup=bool(self._settings.llama_server_disable_warmup),
            disable_webui=bool(self._settings.llama_server_disable_webui),
            threads_batch=max(0, int(self._settings.llama_server_threads_batch)),
            threads_http=max(0, int(self._settings.llama_server_threads_http)),
            extra_args=extra_args,
        )

    def _start_process(self, *, config: LlamaServerLaunchConfig) -> None:
        host, port = self._parse_host_and_port(config.base_url)
        command: list[str] = [
            str(config.executable_path),
            "--host",
            host,
            "--port",
            str(port),
            "--model",
            str(config.model_path),
            "--ctx-size",
            str(config.ctx_size),
            "--batch-size",
            str(config.batch_size),
            "--ubatch-size",
            str(config.ubatch_size),
            "--n-gpu-layers",
            str(config.n_gpu_layers),
            "--flash-attn",
            config.flash_attn,
            "--parallel",
            str(config.parallel_slots),
        ]
        if config.threads > 0:
            command.extend(["--threads", str(config.threads)])
        if config.threads_batch > 0:
            command.extend(["--threads-batch", str(config.threads_batch)])
        if config.threads_http > 0:
            command.extend(["--threads-http", str(config.threads_http)])
        if config.cache_reuse > 0:
            command.extend(["--cache-reuse", str(config.cache_reuse)])
        if config.disable_warmup:
            command.append("--no-warmup")
        if config.disable_webui:
            command.append("--no-webui")
        if config.alias:
            command.extend(["--alias", config.alias])
        if config.extra_args:
            command.extend(config.extra_args)

        log_dir = self._project_root / "backend" / "python_services" / "infrastructure" / "runtime" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        process_log_path = log_dir / "llama_server.log"
        process_log = process_log_path.open("a", encoding="utf-8")

        env = os.environ.copy()
        if config.rocm_library_dir is not None:
            existing_path = str(env.get("PATH", ""))
            env["PATH"] = f"{config.rocm_library_dir};{existing_path}"

        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(config.executable_path.parent),
                stdin=subprocess.DEVNULL,
                stdout=process_log,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                creationflags=creation_flags,
            )
        except Exception:
            process_log.close()
            raise
        self._process = process
        self._process_log_handle = process_log
        self._logger.info(
            "llama_server_autostart_spawned: "
            f"pid={process.pid} endpoint={config.base_url} command={' '.join(command)}"
        )

        ready = self._wait_for_endpoint(
            base_url=config.base_url,
            timeout_seconds=float(config.startup_timeout_ms) / 1000.0,
            process=process,
        )
        if ready:
            self._logger.info(
                "llama_server_autostart_ready: "
                f"pid={process.pid} endpoint={config.base_url}"
            )
            return

        process.poll()
        exit_code = process.returncode
        self.close()
        self._logger.warning(
            "llama_server_autostart_failed: "
            f"endpoint={config.base_url} exit_code={exit_code} log={process_log_path}"
        )

    @staticmethod
    def _split_extra_args(value: str) -> tuple[str, ...]:
        cleaned = value.strip()
        if not cleaned:
            return ()
        try:
            return tuple(shlex.split(cleaned, posix=False))
        except ValueError:
            return tuple(item for item in cleaned.split(" ") if item)

    @staticmethod
    def _parse_host_and_port(base_url: str) -> tuple[str, int]:
        parsed = urlparse(base_url.strip())
        host = str(parsed.hostname or "127.0.0.1")
        if parsed.port is not None:
            port = int(parsed.port)
        else:
            port = 443 if parsed.scheme == "https" else 80
        return host, max(1, min(port, 65535))

    @staticmethod
    def _request_url_candidates(base_url: str) -> tuple[str, ...]:
        normalized = str(base_url or "").strip().rstrip("/")
        if not normalized:
            return ()
        parsed = urlparse(normalized)
        host = parsed.hostname
        port = parsed.port
        scheme = parsed.scheme or "http"
        root = ""
        if host:
            root = f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"
        candidates: list[str] = []
        if root:
            candidates.append(f"{root}/health")
            candidates.append(f"{root}/v1/models")
        candidates.append(f"{normalized}/health")
        candidates.append(f"{normalized}/v1/models")
        deduped: list[str] = []
        for item in candidates:
            if item and item not in deduped:
                deduped.append(item)
        return tuple(deduped)

    def _is_endpoint_ready(self, *, base_url: str, timeout_seconds: float) -> bool:
        for candidate_url in self._request_url_candidates(base_url):
            request = urllib_request.Request(candidate_url, method="GET")
            try:
                with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                    status = int(getattr(response, "status", 0) or 0)
                    if 200 <= status < 500:
                        return True
            except (urllib_error.URLError, TimeoutError, OSError):
                continue
        return False

    def _wait_for_endpoint(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        process: subprocess.Popen[str],
    ) -> bool:
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            if self._is_endpoint_ready(base_url=base_url, timeout_seconds=1.0):
                return True
            time.sleep(0.5)
        return False
