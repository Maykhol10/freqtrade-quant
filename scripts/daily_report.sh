#!/usr/bin/env bash
#
# Resumen diario del dry-run -> Telegram
#
# Lee la API REST local de Freqtrade y manda un mensaje compacto. Se ejecuta
# por cron; no necesita que el bot de Telegram tenga comandos habilitados.
#
#   chmod +x scripts/daily_report.sh
#   crontab -e
#   0 21 * * * cd /opt/freqtrade-quant && ./scripts/daily_report.sh >> user_data/logs/daily_report.log 2>&1
#
# Requiere: curl, jq

set -euo pipefail

cd "$(dirname "$0")/.."

# ---------- Cargar secretos ----------
if [[ ! -f .env ]]; then
  echo "ERROR: falta .env (copia .env.example)" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

TG_TOKEN="${FREQTRADE__TELEGRAM__TOKEN:-}"
TG_CHAT="${FREQTRADE__TELEGRAM__CHAT_ID:-}"
API_USER="${FREQTRADE__API_SERVER__USERNAME:-freq}"
API_PASS="${FREQTRADE__API_SERVER__PASSWORD:-}"

if [[ -z "$TG_TOKEN" || -z "$TG_CHAT" ]]; then
  echo "ERROR: Telegram sin configurar en .env" >&2
  exit 1
fi

API="http://127.0.0.1:8080/api/v1"

api() {
  curl -fsS --max-time 15 -u "${API_USER}:${API_PASS}" "${API}/$1"
}

# ---------- Comprobar que el bot responde ----------
if ! api ping >/dev/null 2>&1; then
  MSG="*ALERTA* El bot no responde en la API local. Revisar \`docker compose ps\`."
  curl -fsS -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    -d chat_id="${TG_CHAT}" -d parse_mode="Markdown" -d text="${MSG}" >/dev/null
  exit 1
fi

# ---------- Recolectar ----------
PROFIT=$(api profit)
DAILY=$(api 'daily?timescale=1')
COUNT=$(api count)
STATUS=$(api status || echo '[]')
PERF=$(api performance || echo '[]')

# ---------- Formatear ----------
read -r TODAY_ABS TODAY_PCT TODAY_TRADES <<<"$(echo "$DAILY" | jq -r '
  (.data[0] // {abs_profit:0, rel_profit:0, trade_count:0})
  | "\(.abs_profit) \(.rel_profit) \(.trade_count)"')"

read -r TOT_ABS TOT_PCT CLOSED WINS LOSSES BEST_PAIR DD <<<"$(echo "$PROFIT" | jq -r '
  "\(.profit_closed_coin // 0) \(.profit_closed_percent_mean // 0) \(.trade_count // 0) \(.winning_trades // 0) \(.losing_trades // 0) \(.best_pair // "-") \(.max_drawdown // 0)"')"

OPEN=$(echo "$COUNT" | jq -r '.current // 0')
MAXT=$(echo "$COUNT" | jq -r '.max // 0')

# Win rate y valor esperado por operacion
if [[ "$CLOSED" -gt 0 ]]; then
  WR=$(awk -v w="$WINS" -v c="$CLOSED" 'BEGIN{printf "%.1f", (w/c)*100}')
  EV=$(awk -v p="$TOT_ABS" -v c="$CLOSED" 'BEGIN{printf "%.4f", p/c}')
else
  WR="n/a"; EV="n/a"
fi

OPEN_LIST=$(echo "$STATUS" | jq -r '
  if length == 0 then "  (ninguna)"
  else .[] | "  \(.pair)  \(.profit_pct)%  (\(.open_date_hum))"
  end')

TOP_PAIRS=$(echo "$PERF" | jq -r '
  if length == 0 then "  (sin datos)"
  else (sort_by(-.profit_abs) | .[:3][] | "  \(.pair): \(.profit_abs) USDT (\(.count) ops)")
  end')

DATE=$(date +%Y-%m-%d)

MSG=$(cat <<EOF
*RESUMEN DIARIO* \`${DATE}\`
_dry-run · TrendPullbackV1_

*Hoy*
  Operaciones: ${TODAY_TRADES}
  P/L: ${TODAY_ABS} USDT (${TODAY_PCT}%)

*Acumulado*
  Cerradas: ${CLOSED}  (${WINS}G / ${LOSSES}P)
  Win rate: ${WR}%
  P/L total: ${TOT_ABS} USDT
  Valor esperado por op: ${EV} USDT
  Max drawdown: ${DD}
  Mejor par: ${BEST_PAIR}

*Abiertas* (${OPEN}/${MAXT})
${OPEN_LIST}

*Top pares*
${TOP_PAIRS}
EOF
)

# ---------- Enviar ----------
curl -fsS -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
  -d chat_id="${TG_CHAT}" \
  -d parse_mode="Markdown" \
  --data-urlencode text="${MSG}" >/dev/null

echo "[$(date -Is)] resumen enviado (${CLOSED} ops cerradas, EV=${EV})"
