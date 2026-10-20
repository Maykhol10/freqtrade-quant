#!/usr/bin/env bash
#
# Bootstrap del servidor. Idempotente: se puede correr varias veces sin romper nada.
#
#   ./scripts/install.sh                                  # interactivo
#   ./scripts/install.sh --telegram-token X --chat-id Y    # desatendido
#   ./scripts/install.sh --skip-docker                     # Docker ya instalado
#
# Qué hace:
#   1. Instala Docker + compose plugin, jq, curl, openssl (si faltan)
#   2. Crea .env con secretos generados al azar (no sobreescribe los que ya existan)
#   3. Ajusta permisos de user_data para el uid 1000 del contenedor
#   4. Descarga la imagen y verifica que la estrategia CARGA de verdad
#   5. Deja listos los comandos siguientes
#
# NO arranca el bot ni descarga datos: eso es decisión tuya (make download / make up).

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

# ------------------------------------------------------------------ #
#  Salida
# ------------------------------------------------------------------ #
if [[ -t 1 ]]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; N=""
fi

step() { echo; echo "${B}==> $*${N}"; }
ok()   { echo "  ${G}OK${N}    $*"; }
warn() { echo "  ${Y}AVISO${N} $*"; }
die()  { echo "  ${R}ERROR${N} $*" >&2; exit 1; }

# ------------------------------------------------------------------ #
#  Argumentos
# ------------------------------------------------------------------ #
TG_TOKEN=""
TG_CHAT=""
SKIP_DOCKER=0
NON_INTERACTIVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --telegram-token) TG_TOKEN="${2:-}"; shift 2 ;;
    --chat-id)        TG_CHAT="${2:-}";  shift 2 ;;
    --skip-docker)    SKIP_DOCKER=1;     shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    -h|--help)        sed -n '2,20p' "$0"; exit 0 ;;
    *)                die "argumento desconocido: $1" ;;
  esac
done

[[ -n "$TG_TOKEN$TG_CHAT" ]] && NON_INTERACTIVE=1

echo "${B}Instalacion de freqtrade-quant${N}"
echo "Directorio: $ROOT"

# ------------------------------------------------------------------ #
#  1. Sistema
# ------------------------------------------------------------------ #
step "1/5  Dependencias del sistema"

[[ "$(uname -s)" == "Linux" ]] || die "este script es para Linux. En Windows usa WSL2 o la VM."
[[ $EUID -ne 0 ]] || warn "estas como root; el bot no lo necesita y es mejor un usuario normal con grupo docker"

if ! command -v sudo >/dev/null 2>&1 && [[ $EUID -ne 0 ]]; then
  die "falta sudo y no eres root"
fi
SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

need_pkgs=()
for cmd in jq curl openssl git; do
  command -v "$cmd" >/dev/null 2>&1 || need_pkgs+=("$cmd")
done

if [[ ${#need_pkgs[@]} -gt 0 ]]; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "  instalando: ${need_pkgs[*]}"
    $SUDO apt-get update -qq
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need_pkgs[@]}"
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y -q "${need_pkgs[@]}"
  else
    die "gestor de paquetes no reconocido. Instala a mano: ${need_pkgs[*]}"
  fi
fi
ok "jq, curl, openssl, git"

# ---------- Docker ----------
if [[ $SKIP_DOCKER -eq 0 ]]; then
  if docker compose version >/dev/null 2>&1; then
    ok "Docker + compose plugin ya presentes ($(docker --version | cut -d, -f1))"
  else
    echo "  instalando Docker desde el repositorio oficial"
    command -v apt-get >/dev/null 2>&1 || die "instala Docker a mano: https://docs.docker.com/engine/install/"

    $SUDO install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | $SUDO gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    $SUDO chmod a+r /etc/apt/keyrings/docker.gpg

    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
      | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null

    $SUDO apt-get update -qq
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      docker-ce docker-ce-cli containerd.io docker-compose-plugin
    ok "Docker instalado"
  fi

  $SUDO systemctl enable --now docker >/dev/null 2>&1 || warn "no pude habilitar docker.service (¿contenedor sin systemd?)"

  if ! docker ps >/dev/null 2>&1; then
    $SUDO usermod -aG docker "$USER"
    warn "te anadi al grupo docker. CIERRA SESION Y VUELVE A ENTRAR (o: newgrp docker) y repite este script"
    exit 1
  fi
  ok "el usuario $USER puede usar docker sin sudo"
fi

# ------------------------------------------------------------------ #
#  2. Secretos
# ------------------------------------------------------------------ #
step "2/5  Archivo .env"

gen() { openssl rand -hex "$1"; }

# Lee un valor existente de .env sin ejecutarlo
envget() {
  [[ -f .env ]] || return 0
  sed -n "s/^$1=\(.*\)$/\1/p" .env | tail -1
}

if [[ -f .env ]]; then
  ok ".env ya existe; solo relleno las claves vacias"
  cp .env ".env.bak.$(date +%Y%m%d%H%M%S)"
else
  cp .env.example .env
  ok ".env creado desde la plantilla"
fi

# Telegram
CUR_TOKEN="$(envget FREQTRADE__TELEGRAM__TOKEN)"
CUR_CHAT="$(envget FREQTRADE__TELEGRAM__CHAT_ID)"

if [[ -z "$CUR_TOKEN" && -z "$TG_TOKEN" && $NON_INTERACTIVE -eq 0 ]]; then
  echo
  echo "  Telegram (Enter para dejarlo en blanco y configurarlo despues):"
  echo "    token:   habla con @BotFather   ->  /newbot"
  echo "    chat_id: habla con @userinfobot ->  copia el numero"
  read -r -p "  Token de Telegram: " TG_TOKEN || true
  read -r -p "  Chat ID: " TG_CHAT || true
fi

setkey() {
  local key="$1" val="$2"
  [[ -n "$val" ]] || return 0
  if grep -q "^${key}=" .env; then
    # delimitador | porque los tokens llevan :
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

[[ -n "$TG_TOKEN" ]] && setkey FREQTRADE__TELEGRAM__TOKEN   "$TG_TOKEN"
[[ -n "$TG_CHAT"  ]] && setkey FREQTRADE__TELEGRAM__CHAT_ID "$TG_CHAT"

# Secretos de la API: se generan si estan vacios
[[ -z "$(envget FREQTRADE__API_SERVER__USERNAME)"       ]] && setkey FREQTRADE__API_SERVER__USERNAME freq
[[ -z "$(envget FREQTRADE__API_SERVER__PASSWORD)"       ]] && setkey FREQTRADE__API_SERVER__PASSWORD "$(gen 16)"
[[ -z "$(envget FREQTRADE__API_SERVER__JWT_SECRET_KEY)" ]] && setkey FREQTRADE__API_SERVER__JWT_SECRET_KEY "$(gen 32)"
[[ -z "$(envget FREQTRADE__API_SERVER__WS_TOKEN)"       ]] && setkey FREQTRADE__API_SERVER__WS_TOKEN "$(gen 16)"

chmod 600 .env
ok "secretos de la API generados (32-64 hex)"

if [[ -z "$(envget FREQTRADE__TELEGRAM__TOKEN)" ]]; then
  warn "Telegram sin configurar: no habra alertas ni resumen diario."
  warn "Rellena FREQTRADE__TELEGRAM__TOKEN y __CHAT_ID en .env cuando puedas."
fi

# En dry-run las claves de Binance deben estar VACIAS
if [[ -n "$(envget FREQTRADE__EXCHANGE__KEY)" ]]; then
  warn "FREQTRADE__EXCHANGE__KEY tiene valor. En dry-run no se necesita."
  warn "Solo ponla cuando completes docs/CHECKLIST_REAL.md."
fi

# ------------------------------------------------------------------ #
#  3. Permisos
# ------------------------------------------------------------------ #
step "3/5  Permisos de user_data"

mkdir -p user_data/{data,logs,strategies,backtest_results,hyperopt_results,plot}

# El contenedor corre como ftuser (uid 1000). Si tu uid ya es 1000, no hace falta.
MYUID="$(id -u)"
if [[ "$MYUID" == "1000" ]]; then
  ok "tu uid ya es 1000, nada que cambiar"
else
  $SUDO chown -R 1000:1000 user_data
  ok "user_data asignado a uid 1000 (tu uid es $MYUID)"
fi

chmod +x scripts/*.sh
ok "scripts ejecutables"

# ------------------------------------------------------------------ #
#  4. Imagen y verificacion real
# ------------------------------------------------------------------ #
step "4/5  Imagen de Freqtrade y carga de la estrategia"

docker compose pull -q 2>/dev/null || docker compose pull
ok "imagen descargada: $(docker compose run --rm --no-deps freqtrade --version 2>/dev/null | tail -1)"

echo "  comprobando que las estrategias importan de verdad..."
STRATS="$(docker compose run --rm --no-deps freqtrade list-strategies \
            --config user_data/config.json 2>&1 || true)"

for s in TrendPullbackV1 BuyAndHoldBTC; do
  if echo "$STRATS" | grep -q "$s"; then
    ok "$s carga correctamente"
  else
    echo "$STRATS" | tail -30
    die "$s NO carga. Revisa el error de arriba antes de seguir."
  fi
done

echo "  validando config.json..."
docker compose run --rm --no-deps freqtrade show-config \
  --config user_data/config.json >/dev/null 2>&1 \
  && ok "config.json valido para Freqtrade" \
  || die "config.json rechazado. Corre: docker compose run --rm freqtrade show-config --config user_data/config.json"

# ------------------------------------------------------------------ #
#  5. Resumen
# ------------------------------------------------------------------ #
step "5/5  Listo"

cat <<EOF

  ${G}Instalacion completa.${N} El bot NO esta corriendo todavia (a proposito).

  Siguiente, en este orden:

    make download          # datos 1h + 4h desde 2023-01-01   (~5 min)
    make download-detail   # datos 5m para simular stops       (~15 min)
    make audit             # ${B}BLOQUEANTE${N}: lookahead + recursive
    make backtest-in       # primer backtest in-sample
    make stress            # comisiones 0.1% / 0.15% / 0.2%
    make benchmark-in      # comprar y mantener BTC

  Solo si 'make audit' sale limpio tiene sentido mirar rentabilidades.

  Opcional, cuando decidas arrancar el dry-run:

    make preflight         # 12 comprobaciones del servidor
    make up                # arranca el bot
    make cron-install      # resumen diario + vigilancia + respaldo

  Documentacion:
    docs/SERVIDOR.md       despliegue, firewall, diagnostico
    docs/COMANDOS.md       cada comando explicado
    docs/VALIDACION.md     umbrales y plantilla de metricas
    docs/CHECKLIST_REAL.md antes de poner dinero real

EOF
