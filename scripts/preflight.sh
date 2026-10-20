#!/usr/bin/env bash
#
# Verificacion previa al dry-run. 12 comprobaciones sobre el servidor y la config.
#
#   ./scripts/preflight.sh
#
# Salida 0 = todo en orden.  Salida 1 = hay fallos que impiden operar.
# Los AVISO no bloquean, pero conviene resolverlos.

set -uo pipefail

cd "$(dirname "$0")/.."

if [[ -t 1 ]]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; N=""
fi

PASS=0; FAIL=0; WARN=0

pass() { printf "  ${G}PASS${N}  %-34s %s\n" "$1" "${2:-}"; PASS=$((PASS+1)); }
fail() { printf "  ${R}FALLA${N} %-34s %s\n" "$1" "${2:-}"; FAIL=$((FAIL+1)); }
warn() { printf "  ${Y}AVISO${N} %-34s %s\n" "$1" "${2:-}"; WARN=$((WARN+1)); }

echo "${B}Preflight · freqtrade-quant${N}"
echo "$(date -Is)"
echo

# ------------------------------------------------------------------ #
echo "${B}Infraestructura${N}"
# ------------------------------------------------------------------ #

# 1. Docker
if docker compose version >/dev/null 2>&1; then
  pass "docker compose" "$(docker --version | cut -d, -f1)"
else
  fail "docker compose" "no disponible; corre scripts/install.sh"
fi

# 2. Espacio en disco. Los datos de 5m de 3 anos pesan ~1 GB por par.
AVAIL_KB=$(df -Pk . | awk 'NR==2 {print $4}')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
USE_PCT=$(df -Pk . | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
if [[ $AVAIL_GB -ge 5 ]]; then
  pass "espacio en disco" "${AVAIL_GB} GB libres (${USE_PCT}% usado)"
elif [[ $AVAIL_GB -ge 2 ]]; then
  warn "espacio en disco" "solo ${AVAIL_GB} GB libres; los datos de 5m necesitan ~2 GB"
else
  fail "espacio en disco" "${AVAIL_GB} GB libres: insuficiente"
fi

# 3. RAM. El contenedor tiene limite de 1 GB; con menos de 1.5 GB total hay riesgo de OOM.
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
SWAP_MB=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
if [[ $MEM_MB -ge 2000 ]]; then
  pass "memoria" "${MEM_MB} MB RAM + ${SWAP_MB} MB swap"
elif [[ $MEM_MB -ge 1500 || $SWAP_MB -ge 1000 ]]; then
  warn "memoria" "${MEM_MB} MB RAM + ${SWAP_MB} MB swap; hyperopt puede morir por OOM"
else
  fail "memoria" "${MEM_MB} MB RAM sin swap suficiente; anade swap (docs/SERVIDOR.md)"
fi

# 4. Reloj. Un desfase > 1 s rompe las firmas de Binance.
if command -v timedatectl >/dev/null 2>&1; then
  SYNC=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo "no")
  TZ_NOW=$(timedatectl show -p Timezone --value 2>/dev/null || echo "?")
  if [[ "$SYNC" == "yes" ]]; then
    pass "reloj sincronizado (NTP)" "zona: ${TZ_NOW}"
  else
    fail "reloj sincronizado (NTP)" "sin sincronizar; Binance rechazara las ordenes"
  fi
else
  warn "reloj sincronizado (NTP)" "timedatectl no disponible; verifica a mano"
fi

# ------------------------------------------------------------------ #
echo
echo "${B}Seguridad${N}"
# ------------------------------------------------------------------ #

# 5. .env existe y con permisos restrictivos
if [[ -f .env ]]; then
  PERM=$(stat -c '%a' .env 2>/dev/null || echo "???")
  if [[ "$PERM" == "600" ]]; then
    pass "permisos de .env" "600"
  else
    warn "permisos de .env" "$PERM; deberia ser 600 (chmod 600 .env)"
  fi
else
  fail "existe .env" "falta; corre scripts/install.sh"
fi

# 6. .env fuera de git
if git rev-parse --git-dir >/dev/null 2>&1; then
  if git check-ignore -q .env 2>/dev/null; then
    if git ls-files --error-unmatch .env >/dev/null 2>&1; then
      fail ".env fuera de git" "esta IGNORADO pero YA FUE COMMITEADO. Rota los secretos."
    else
      pass ".env fuera de git" "ignorado y sin rastrear"
    fi
  else
    fail ".env fuera de git" "NO esta ignorado: riesgo de subir secretos"
  fi
else
  warn ".env fuera de git" "no es un repo git"
fi

# 7. API no expuesta a internet
PORTMAP=$(grep -E '^\s*-\s*"?[0-9.]*:?8080:8080' docker-compose.yml 2>/dev/null | tr -d ' "-')
if [[ "$PORTMAP" == 127.0.0.1:* ]]; then
  pass "API atada a loopback" "$PORTMAP"
else
  fail "API atada a loopback" "mapeo '$PORTMAP': accesible desde la red"
fi

# Si el bot ya corre, comprobar el socket de verdad
if command -v ss >/dev/null 2>&1; then
  LISTEN=$(ss -tlnH 2>/dev/null | awk '$4 ~ /:8080$/ {print $4}' | head -1)
  if [[ -n "$LISTEN" ]]; then
    case "$LISTEN" in
      127.0.0.1:*|[::1]:*) pass "socket 8080 en escucha" "$LISTEN" ;;
      *)                   fail "socket 8080 en escucha" "$LISTEN expuesto; cierra el puerto" ;;
    esac
  fi
fi

# 8. Password de la API no vacio
if [[ -f .env ]]; then
  APIPASS=$(sed -n 's/^FREQTRADE__API_SERVER__PASSWORD=\(.*\)$/\1/p' .env | tail -1)
  if [[ ${#APIPASS} -ge 12 ]]; then
    pass "password de la API" "${#APIPASS} caracteres"
  else
    fail "password de la API" "vacio o demasiado corto"
  fi
fi

# ------------------------------------------------------------------ #
echo
echo "${B}Configuracion del bot${N}"
# ------------------------------------------------------------------ #

# 9. dry_run activo. La comprobacion que impide perder dinero por accidente.
if command -v jq >/dev/null 2>&1 && [[ -f user_data/config.json ]]; then
  DRY=$(jq -r '.dry_run' user_data/config.json)
  STAKE=$(jq -r '.stake_amount' user_data/config.json)
  MAXT=$(jq -r '.max_open_trades' user_data/config.json)
  WALLET=$(jq -r '.dry_run_wallet' user_data/config.json)
  if [[ "$DRY" == "true" ]]; then
    pass "dry_run activo" "wallet ${WALLET} USDT · ${MAXT} x ${STAKE} USDT"
  else
    warn "dry_run activo" "${R}DRY_RUN DESACTIVADO: OPERA CON DINERO REAL${N}"
  fi

  # Capital coherente con la exposicion maxima
  NEED=$(awk -v s="$STAKE" -v m="$MAXT" 'BEGIN{print s*m}')
  if awk -v n="$NEED" -v w="$WALLET" 'BEGIN{exit !(n <= w)}'; then
    pass "capital suficiente" "expone ${NEED} de ${WALLET} USDT"
  else
    fail "capital suficiente" "necesita ${NEED} USDT y solo hay ${WALLET}"
  fi

  # Claves de Binance vacias en config.json (deben vivir en .env)
  KEYLEN=$(jq -r '.exchange.key | length' user_data/config.json)
  if [[ "$KEYLEN" == "0" ]]; then
    pass "sin claves en config.json" "los secretos van en .env"
  else
    fail "sin claves en config.json" "hay una API key en el JSON versionado"
  fi
else
  fail "config.json legible" "falta jq o el archivo"
fi

# 10. Estrategia presente
if [[ -f user_data/strategies/TrendPullbackV1.py ]]; then
  pass "estrategia presente" "TrendPullbackV1.py"
else
  fail "estrategia presente" "falta user_data/strategies/TrendPullbackV1.py"
fi

# 11. Datos descargados
CANDLES=$(find user_data/data -name '*1h*' 2>/dev/null | wc -l)
CANDLES_4H=$(find user_data/data -name '*4h*' 2>/dev/null | wc -l)
if [[ $CANDLES -ge 2 && $CANDLES_4H -ge 2 ]]; then
  SIZE=$(du -sh user_data/data 2>/dev/null | cut -f1)
  pass "datos de mercado" "${CANDLES} series 1h + ${CANDLES_4H} series 4h (${SIZE})"
elif [[ $CANDLES -gt 0 ]]; then
  warn "datos de mercado" "incompletos: faltan series; corre make download"
else
  warn "datos de mercado" "sin descargar; corre make download"
fi

# 12. Telegram operativo
if [[ -f .env ]]; then
  TGT=$(sed -n 's/^FREQTRADE__TELEGRAM__TOKEN=\(.*\)$/\1/p' .env | tail -1)
  TGC=$(sed -n 's/^FREQTRADE__TELEGRAM__CHAT_ID=\(.*\)$/\1/p' .env | tail -1)
  if [[ -n "$TGT" && -n "$TGC" ]]; then
    if curl -fsS --max-time 10 "https://api.telegram.org/bot${TGT}/getMe" >/dev/null 2>&1; then
      pass "Telegram responde" "token valido"
    else
      fail "Telegram responde" "el token no valida contra la API de Telegram"
    fi
  else
    warn "Telegram configurado" "sin token o chat_id: no habra alertas"
  fi
fi

# ------------------------------------------------------------------ #
echo
echo "${B}Resultado${N}"
printf "  %s%d PASS%s   %s%d AVISO%s   %s%d FALLA%s\n" \
  "$G" "$PASS" "$N" "$Y" "$WARN" "$N" "$R" "$FAIL" "$N"
echo

if [[ $FAIL -gt 0 ]]; then
  echo "  ${R}Hay fallos. Resuelvelos antes de arrancar el bot.${N}"
  exit 1
fi
if [[ $WARN -gt 0 ]]; then
  echo "  ${Y}Sin fallos, pero revisa los avisos.${N}"
else
  echo "  ${G}Todo en orden. Puedes arrancar con: make up${N}"
fi
exit 0
