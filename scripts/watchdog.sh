#!/usr/bin/env bash
#
# Vigilancia del bot. Pensado para cron cada 15 minutos.
#
#   */15 * * * * cd /opt/freqtrade-quant && ./scripts/watchdog.sh >> user_data/logs/watchdog.log 2>&1
#
# Avisa por Telegram si:
#   - el contenedor no esta corriendo
#   - la API local no responde
#   - el disco pasa del 85%
#   - el bot no procesa velas desde hace mas de 2 horas (bot colgado)
#
# Evita el spam: no repite la misma alerta antes de 2 horas.

set -uo pipefail

cd "$(dirname "$0")/.."

STATE_DIR="user_data/logs/.watchdog"
mkdir -p "$STATE_DIR"
COOLDOWN=7200   # 2 horas entre alertas iguales

[[ -f .env ]] || { echo "falta .env"; exit 1; }
# shellcheck disable=SC1091
set -a; source .env; set +a

TG_TOKEN="${FREQTRADE__TELEGRAM__TOKEN:-}"
TG_CHAT="${FREQTRADE__TELEGRAM__CHAT_ID:-}"
API_USER="${FREQTRADE__API_SERVER__USERNAME:-freq}"
API_PASS="${FREQTRADE__API_SERVER__PASSWORD:-}"

alert() {
  local key="$1" msg="$2"
  local stamp="$STATE_DIR/$key"
  local now; now=$(date +%s)

  if [[ -f "$stamp" ]]; then
    local last; last=$(cat "$stamp" 2>/dev/null || echo 0)
    if (( now - last < COOLDOWN )); then
      echo "[$(date -Is)] $key: silenciado (alerta reciente)"
      return
    fi
  fi
  echo "$now" > "$stamp"

  echo "[$(date -Is)] ALERTA $key: $msg"
  [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]] || return
  curl -fsS -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    -d chat_id="${TG_CHAT}" -d parse_mode="Markdown" \
    --data-urlencode text="*WATCHDOG* \`$(hostname)\`

${msg}" >/dev/null 2>&1 || true
}

clear_alert() { rm -f "$STATE_DIR/$1"; }

PROBLEMS=0

# ---------- 1. Contenedor vivo ----------
if ! docker compose ps --status running 2>/dev/null | grep -q freqtrade; then
  alert container "El contenedor no esta corriendo.
Revisa: \`docker compose logs --tail 50\`"
  PROBLEMS=1
  # Sin contenedor las demas comprobaciones no aplican
  exit $PROBLEMS
fi
clear_alert container

# ---------- 2. API responde ----------
if ! curl -fsS --max-time 10 -u "${API_USER}:${API_PASS}" \
       "http://127.0.0.1:8080/api/v1/ping" >/dev/null 2>&1; then
  alert api "El contenedor corre pero la API no responde.
Posible cuelgue. Revisa los logs o reinicia."
  PROBLEMS=1
else
  clear_alert api

  # ---------- 3. ¿Procesa velas? ----------
  # /api/v1/status devuelve las operaciones abiertas; /sysinfo no da el ultimo ciclo,
  # asi que usamos la edad de la ultima linea del log como senal de vida.
  LOG="user_data/logs/freqtrade.log"
  if [[ -f "$LOG" ]]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$LOG") ))
    if (( AGE > 7200 )); then
      alert stale "El log no se escribe desde hace $((AGE/3600))h.
El bot puede estar colgado sin haber muerto."
      PROBLEMS=1
    else
      clear_alert stale
    fi
  fi

  # ---------- 4. Errores recientes en el log ----------
  if [[ -f "$LOG" ]]; then
    ERRS=$(tail -500 "$LOG" 2>/dev/null | grep -c ' ERROR ' || true)
    if (( ERRS > 20 )); then
      alert errors "${ERRS} lineas ERROR en las ultimas 500 del log.
Revisa: \`tail -100 ${LOG} | grep ERROR\`"
      PROBLEMS=1
    else
      clear_alert errors
    fi
  fi
fi

# ---------- 5. Disco ----------
USE=$(df -Pk . | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
if (( USE >= 85 )); then
  alert disk "Disco al ${USE}%.
Limpia datos viejos: \`du -sh user_data/*\`"
  PROBLEMS=1
else
  clear_alert disk
fi

if (( PROBLEMS == 0 )); then
  echo "[$(date -Is)] todo en orden (disco ${USE}%)"
fi
exit $PROBLEMS
