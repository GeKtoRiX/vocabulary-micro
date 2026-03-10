# CONTINUITY.md

## Current Task
Перевод Python NLP-сервисов на AMD ROCm GPU + изоляция всех ML-зависимостей в Docker-контейнеры.

## Progress
95%

## What Was Done
1. **GPU-поддержка (ROCm / RX 7600 XT)**
   - `backend/python_services/infrastructure/sqlite/tokenizer.py` — `spacy.prefer_gpu()` при импорте
   - `backend/python_services/nlp_service/main.py` — подавление ROCm UserWarnings, `TOKENIZERS_PARALLELISM=false`
   - `backend/python_services/infrastructure/bootstrap/llama_server_runtime.py` — исправлен разделитель PATH (`;`→`:`), добавлен `LD_LIBRARY_PATH` для ROCm `.so`
   - `.env` — `HSA_OVERRIDE_GFX_VERSION=11.0.0`, `BERT_DEVICE=cuda`, `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`

2. **NLTK данные в Docker**
   - `docker/download_nltk_data.py` — скачивает и распаковывает wordnet, punkt, omw-1.4, punkt_tab, averaged_perceptron_tagger_eng
   - `docker/Dockerfile.python-runtime` — добавлены NLTK_DATA и шаг загрузки NLTK
   - `docker/Dockerfile.python-runtime-rocm` — новый Dockerfile с 5 шагами: PyTorch ROCm → NLP deps → NLTK → spaCy en_core_web_trf → SBERT all-MiniLM-L6-v2

3. **Изоляция зависимостей в Docker**
   - `start.sh` — авто-определение `PYTHON_BACKEND` (docker/native), GPU-флаги для BERT_DEVICE=cuda, `exec docker run --network host` для NLP/export сервисов
   - `scripts/prepare_docker_runtime.sh` — флаг `--rocm` для сборки GPU-образа
   - `docker-compose.rocm.yml` — override для AMD GPU devices, group_add

4. **Вспомогательные скрипты**
   - `scripts/grant_gpu_access.sh` — `setfacl` доступ к GPU без перезапуска сессии
   - `requirements.rocm.txt` — справочный файл для ручной установки ROCm-зависимостей

## Current State
- `vocabulary-python-runtime:local` (CPU) — **готов**
- `vocabulary-node-runtime:local` — **готов**
- `vocabulary-python-runtime-rocm:local` (GPU) — **НЕ собран** (требует `./scripts/prepare_docker_runtime.sh --rocm`, ~10-30 мин + 3GB)
- CPU Docker-режим работает (`BERT_DEVICE=cpu` → auto-detect → docker)
- GPU режим после сборки ROCm-образа: `BERT_DEVICE=cuda` в `.env`, затем `./start.sh`

## Next Step
Собрать ROCm Docker-образ (когда нужен GPU):
```bash
./scripts/prepare_docker_runtime.sh --rocm
```
Затем запустить: `./start.sh` (авто-определит ROCm-образ при BERT_DEVICE=cuda).

## Last Updated
2026-03-11
