#!/usr/bin/env bash
#
# Instala las tareas programadas del proyecto en el crontab del usuario.
#
#   ./scripts/cron-install.sh            # instalar / actualizar
#   ./scripts/cron-install.sh --remove   # quitar
#   ./scripts/cron-install.sh --show     # ver lo que hay
#
# Idempotente: reemplaza su propio bloque y no toca el resto del crontab.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

MARK_START="# >>> freqtrade-quant >>>"
MARK_END="# <<< freqtrade-quant <<<"

# Hora del resumen diario: zona horaria del sistema
REPORT_HOUR="${REPORT_HOUR:-21}"

show() {
  echo "Crontab actual del bloque freqtrade-quant:"
  crontab -l 2>/dev/null | sed -n "/$MARK_START/,/$MARK_END/p" || echo "  (no instalado)"
}

strip_block() {
  crontab -l 2>/dev/null | sed "/$MARK_START/,/$MARK_END/d" || true
}

case "${1:-}" in
  --show)
    show; exit 0 ;;
  --remove)
    strip_block | crontab -
    echo "Tareas de freqtrade-quant eliminadas del crontab."
    exit 0 ;;
  "") ;;
  *) echo "uso: $0 [--remove|--show]" >&2; exit 1 ;;
esac

command -v crontab >/dev/null 2>&1 || {
  echo "ERROR: falta crontab. En Ubuntu: sudo apt install -y cron" >&2
  exit 1
}

BLOCK="$MARK_START
# Generado por scripts/cron-install.sh el $(date -Is)
# Resumen diario a Telegram (${REPORT_HOUR}:00 hora del sistema)
0 ${REPORT_HOUR} * * * cd ${ROOT} && ./scripts/daily_report.sh >> user_data/logs/daily_report.log 2>&1
# Vigilancia cada 15 minutos (contenedor, API, disco, cuelgues)
*/15 * * * * cd ${ROOT} && ./scripts/watchdog.sh >> user_data/logs/watchdog.log 2>&1
# Respaldo semanal, domingos 04:00
0 4 * * 0 cd ${ROOT} && ./scripts/backup.sh >> user_data/logs/backup.log 2>&1
# Actualizar datos de mercado, lunes 05:00 (incremental)
0 5 * * 1 cd ${ROOT} && docker compose run --rm freqtrade download-data --config user_data/config.json --exchange binance --trading-mode spot --pairs BTC/USDT ETH/USDT --timeframes 1h 4h 5m --days 14 >> user_data/logs/download.log 2>&1
# Rotar logs propios de los scripts (los del contenedor los rota Docker)
0 6 1 * * cd ${ROOT} && find user_data/logs -name '*.log' -size +20M -exec truncate -s 0 {} \\;
$MARK_END"

{ strip_block; echo "$BLOCK"; } | crontab -

echo "Tareas instaladas:"
echo
show
echo
cat <<EOF
  Comprobaciones utiles:
    ./scripts/daily_report.sh      # probar el resumen a mano
    ./scripts/watchdog.sh          # probar la vigilancia
    tail -f user_data/logs/watchdog.log

  Si el resumen diario no llega:
    1. systemctl status cron       (el servicio tiene que estar activo)
    2. grep CRON /var/log/syslog | tail
    3. ./scripts/preflight.sh      (verifica el token de Telegram)
EOF
