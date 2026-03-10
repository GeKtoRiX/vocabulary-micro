"""Internal NLP service entry point."""
from __future__ import annotations

import os
import warnings

# Подавить ожидаемые предупреждения PyTorch ROCm для gfx1102 (RX 7600 XT).
# hipBLASLt не поддерживает gfx1102 и автоматически откатывается на hipBLAS —
# это штатное поведение, предупреждение информационное.
# Flash/Memory Efficient Attention для Navi31 экспериментальны, но работают
# после установки TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1.
warnings.filterwarnings(
    "ignore",
    message=r".*hipBLASLt.*unsupported architecture.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r".*(Flash|Memory Efficient) attention.*Navi31.*experimental.*",
    category=UserWarning,
)

# Отключить параллелизм токенизатора в дочернем процессе (uvicorn workers).
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "backend.python_services.nlp_service.app:app",
        host=os.getenv("NLP_SERVICE_HOST", "127.0.0.1"),
        port=int(os.getenv("NLP_SERVICE_PORT", "8767")),
        reload=False,
    )
