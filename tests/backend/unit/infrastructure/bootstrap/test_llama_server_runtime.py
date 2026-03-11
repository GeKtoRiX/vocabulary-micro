from __future__ import annotations

from pathlib import Path

import pytest

from backend.python_services.infrastructure.bootstrap.llama_server_runtime import LlamaCppServerManager
from backend.python_services.infrastructure.config.settings import PipelineSettings


class _LoggerStub:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.messages.append(("info", message))

    def warning(self, message: str) -> None:
        self.messages.append(("warning", message))


def test_parse_host_and_port_from_base_url() -> None:
    host, port = LlamaCppServerManager._parse_host_and_port("http://127.0.0.1:1234/v1")
    assert host == "127.0.0.1"
    assert port == 1234


def test_split_extra_args() -> None:
    args = LlamaCppServerManager._split_extra_args("--no-mmap --flash-attn")
    assert args == ("--no-mmap", "--flash-attn")


def test_build_launch_config_rejects_missing_executable(tmp_path: Path) -> None:
    logger = _LoggerStub()
    manager = LlamaCppServerManager(
        settings=PipelineSettings(
            enable_third_pass_llm=True,
            llama_server_autostart_enabled=True,
            llama_server_executable="tools/llama/llama-server.exe",
            llama_server_model_path="model.gguf",
        ),
        project_root=tmp_path,
        logger=logger,  # type: ignore[arg-type]
    )
    config = manager._build_launch_config(base_url="http://127.0.0.1:1234")
    assert config is None
    assert any(
        level == "warning" and "executable not found" in message
        for level, message in logger.messages
    )


def test_build_launch_config_resolves_relative_paths(tmp_path: Path) -> None:
    logger = _LoggerStub()
    exe_dir = tmp_path / "tools" / "llama"
    exe_dir.mkdir(parents=True, exist_ok=True)
    executable_path = exe_dir / "llama-server.exe"
    executable_path.write_text("stub", encoding="utf-8")
    model_path = tmp_path / "models" / "llama.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("stub", encoding="utf-8")

    manager = LlamaCppServerManager(
        settings=PipelineSettings(
            enable_third_pass_llm=True,
            llama_server_autostart_enabled=True,
            llama_server_executable="tools/llama/llama-server.exe",
            llama_server_model_path="models/llama.gguf",
            llama_server_n_gpu_layers=-1,
            llama_server_ctx_size=4096,
            llama_server_batch_size=256,
            llama_server_ubatch_size=128,
        ),
        project_root=tmp_path,
        logger=logger,  # type: ignore[arg-type]
    )
    config = manager._build_launch_config(base_url="http://127.0.0.1:1234")
    assert config is not None
    assert config.executable_path == executable_path.resolve()
    assert config.model_path == model_path.resolve()
    assert config.n_gpu_layers == -1
    assert config.ctx_size == 4096
    assert config.flash_attn == "on"
    assert config.parallel_slots == 1
    assert config.cache_reuse == 256
    assert config.disable_warmup is True
    assert config.disable_webui is True


def test_is_server_alive_reflects_managed_process_state(tmp_path: Path) -> None:
    logger = _LoggerStub()
    manager = LlamaCppServerManager(
        settings=PipelineSettings(),
        project_root=tmp_path,
        logger=logger,  # type: ignore[arg-type]
    )

    class _ProcessStub:
        def __init__(self, return_code: int | None) -> None:
            self.returncode = return_code

        def poll(self) -> int | None:
            return self.returncode

    manager._process = _ProcessStub(return_code=None)  # type: ignore[assignment]
    assert manager.is_server_alive() is True

    manager._process = _ProcessStub(return_code=1)  # type: ignore[assignment]
    assert manager.is_server_alive() is False


def test_ensure_started_restarts_unhealthy_managed_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = _LoggerStub()
    manager = LlamaCppServerManager(
        settings=PipelineSettings(
            enable_third_pass_llm=True,
            llama_server_autostart_enabled=True,
            third_pass_llm_base_url="http://127.0.0.1:1234",
        ),
        project_root=tmp_path,
        logger=logger,  # type: ignore[arg-type]
    )

    class _ProcessStub:
        returncode = None

        @staticmethod
        def poll() -> int | None:
            return None

    manager._process = _ProcessStub()  # type: ignore[assignment]
    close_calls: list[str] = []
    start_calls: list[object] = []

    def _close() -> None:
        close_calls.append("closed")
        manager._process = None

    def _start_process(*, config: object) -> None:
        start_calls.append(config)

    monkeypatch.setattr(manager, "close", _close)
    monkeypatch.setattr(manager, "_is_endpoint_ready", lambda *, base_url, timeout_seconds: False)
    monkeypatch.setattr(manager, "_build_launch_config", lambda *, base_url: object())
    monkeypatch.setattr(manager, "_start_process", _start_process)

    manager.ensure_started()

    assert close_calls == ["closed"]
    assert len(start_calls) == 1
