#!/usr/bin/env bash
# Выдать доступ к AMD ROCm GPU текущему пользователю без перезапуска сессии.
# Работает немедленно для всех уже запущенных процессов (в т.ч. Claude Code).
#
# Запуск: sudo bash scripts/grant_gpu_access.sh
set -euo pipefail

USER_TO_GRANT="${1:-$SUDO_USER}"

if [ -z "$USER_TO_GRANT" ]; then
  echo "Использование: sudo bash $0 <username>"
  echo "Или запустить через sudo — имя пользователя подхватится из SUDO_USER."
  exit 1
fi

echo "[gpu-access] Выдаём ACL-права на GPU-устройства пользователю: ${USER_TO_GRANT}"

# /dev/kfd — HSA Kernel Fusion Driver (нужен ROCm/HIP)
if [ -e /dev/kfd ]; then
  setfacl -m "u:${USER_TO_GRANT}:rw" /dev/kfd
  echo "[gpu-access] /dev/kfd — OK"
else
  echo "[gpu-access] /dev/kfd — не найден (ROCm драйвер не установлен?)"
fi

# /dev/dri/renderD* — render-устройства GPU
for dev in /dev/dri/renderD*; do
  if [ -e "$dev" ]; then
    setfacl -m "u:${USER_TO_GRANT}:rw" "$dev"
    echo "[gpu-access] ${dev} — OK"
  fi
done

# /dev/dri/card* — опционально (нужен для некоторых display операций)
for dev in /dev/dri/card*; do
  if [ -e "$dev" ]; then
    setfacl -m "u:${USER_TO_GRANT}:rw" "$dev"
    echo "[gpu-access] ${dev} — OK"
  fi
done

echo ""
echo "[gpu-access] Готово. Проверка:"
echo "  HSA_OVERRIDE_GFX_VERSION=11.0.0 python3 -c \\"
echo "    \"import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))\""
