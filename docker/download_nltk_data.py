"""Скачать и распаковать NLTK данные во время сборки Docker-образа."""
import nltk
import os
import pathlib
import zipfile

NLTK_PACKAGES = [
    "wordnet",
    "omw-1.4",
    "punkt",
    "punkt_tab",
    "averaged_perceptron_tagger_eng",
]

# Явно задать директорию загрузки — уважает NLTK_DATA из окружения.
download_dir = os.environ.get("NLTK_DATA", nltk.data.path[0])
pathlib.Path(download_dir).mkdir(parents=True, exist_ok=True)

print(f"[nltk] Директория: {download_dir}")
print("[nltk] Скачиваем пакеты...")
for pkg in NLTK_PACKAGES:
    result = nltk.download(pkg, download_dir=download_dir, quiet=False)
    print(f"[nltk] {pkg}: {'OK' if result else 'already up-to-date'}")

# NLTK скачивает в виде .zip — распаковать, чтобы find() работал без ZipFilePathPointer
print("[nltk] Распаковываем архивы...")
for zf_path in pathlib.Path(download_dir).rglob("*.zip"):
    dest = zf_path.parent / zf_path.stem
    if not dest.exists():
        print(f"[nltk] Распаковываем {zf_path.name}")
        with zipfile.ZipFile(zf_path) as zf:
            zf.extractall(zf_path.parent)

# Проверка
from nltk.corpus import wordnet as wn  # noqa: E402
synsets = wn.synsets("run")
assert len(synsets) > 0, "wordnet не работает"
nltk.data.find("tokenizers/punkt_tab")
print(f"[nltk] Проверка: wordnet={len(synsets)} synsets, punkt_tab=OK")
