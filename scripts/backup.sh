#!/usr/bin/env bash
#
# Respaldo de lo que NO se puede volver a generar.
#
#   ./scripts/backup.sh [destino]
#   0 4 * * 0  cd /opt/freqtrade-quant && ./scripts/backup.sh >> user_data/logs/backup.log 2>&1
#
# Guarda: base de datos de operaciones, config, estrategias, .env cifrado,
#         resultados de backtest. NO guarda los datos de mercado (se re-descargan).
#
# Conserva los ultimos 8 respaldos y borra los mas viejos.

set -euo pipefail

cd "$(dirname "$0")/.."

DEST="${1:-$HOME/freqtrade-backups}"
KEEP=8
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="freqtrade-quant-${STAMP}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$DEST"
mkdir -p "$TMP/$NAME"

echo "[$(date -Is)] respaldo -> $DEST/$NAME.tar.gz"

# ---------- Base de datos de operaciones ----------
# Se copia con la API de sqlite para no capturar un archivo a medio escribir.
for db in user_data/*.sqlite; do
  [[ -e "$db" ]] || continue
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$db" ".backup '$TMP/$NAME/$(basename "$db")'"
    echo "  db (consistente): $(basename "$db")"
  else
    cp "$db" "$TMP/$NAME/"
    echo "  db (copia simple, instala sqlite3 para una copia consistente): $(basename "$db")"
  fi
done

# ---------- Configuracion y codigo ----------
mkdir -p "$TMP/$NAME/user_data"
cp user_data/config.json "$TMP/$NAME/user_data/" 2>/dev/null || true
cp -r user_data/strategies "$TMP/$NAME/user_data/" 2>/dev/null || true
cp docker-compose.yml Makefile "$TMP/$NAME/" 2>/dev/null || true
echo "  config, estrategias y compose"

# Parametros de hyperopt aplicados (el .json junto a la estrategia)
find user_data/strategies -name '*.json' -exec cp {} "$TMP/$NAME/user_data/strategies/" \; 2>/dev/null || true

# ---------- Resultados de backtest ----------
if [[ -d user_data/backtest_results ]] && [[ -n "$(ls -A user_data/backtest_results 2>/dev/null)" ]]; then
  mkdir -p "$TMP/$NAME/user_data/backtest_results"
  cp user_data/backtest_results/*.json "$TMP/$NAME/user_data/backtest_results/" 2>/dev/null || true
  echo "  resultados de backtest"
fi

# ---------- .env ----------
# Nunca en claro dentro del tar. Si hay gpg se cifra; si no, se omite.
if [[ -f .env ]]; then
  if command -v gpg >/dev/null 2>&1; then
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase-file <(echo "${BACKUP_PASSPHRASE:-}") \
        -o "$TMP/$NAME/env.gpg" .env 2>/dev/null \
      && echo "  .env cifrado (AES256)" \
      || { rm -f "$TMP/$NAME/env.gpg"
           echo "  .env OMITIDO: define BACKUP_PASSPHRASE para cifrarlo"; }
  else
    echo "  .env OMITIDO: instala gnupg para incluirlo cifrado"
  fi
  # Siempre guardamos la lista de claves presentes, sin sus valores.
  sed 's/=.*/=<definido>/' .env > "$TMP/$NAME/env.keys.txt"
fi

# ---------- Metadatos ----------
{
  echo "fecha:    $(date -Is)"
  echo "host:     $(hostname)"
  echo "commit:   $(git rev-parse --short HEAD 2>/dev/null || echo 'sin git')"
  echo "rama:     $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
  echo "imagen:   $(docker compose config --images 2>/dev/null | head -1)"
  echo
  echo "--- estado del bot ---"
  docker compose ps 2>/dev/null || true
} > "$TMP/$NAME/INFO.txt"

# ---------- Empaquetar ----------
tar -czf "$DEST/$NAME.tar.gz" -C "$TMP" "$NAME"
SIZE=$(du -h "$DEST/$NAME.tar.gz" | cut -f1)
echo "  creado: $NAME.tar.gz ($SIZE)"

# ---------- Rotacion ----------
TOTAL=$(find "$DEST" -maxdepth 1 -name 'freqtrade-quant-*.tar.gz' | wc -l)
if (( TOTAL > KEEP )); then
  find "$DEST" -maxdepth 1 -name 'freqtrade-quant-*.tar.gz' -printf '%T@ %p\n' \
    | sort -n | head -n $(( TOTAL - KEEP )) | cut -d' ' -f2- \
    | while read -r old; do rm -f "$old"; echo "  rotado (borrado): $(basename "$old")"; done
fi

echo "[$(date -Is)] respaldo completo. Total en $DEST: $(find "$DEST" -maxdepth 1 -name 'freqtrade-quant-*.tar.gz' | wc -l)"

cat <<'EOF'

  Para restaurar:
    tar -xzf freqtrade-quant-FECHA.tar.gz
    cp freqtrade-quant-FECHA/tradesv3.dryrun.sqlite user_data/
    gpg -d freqtrade-quant-FECHA/env.gpg > .env && chmod 600 .env

  Este respaldo vive en la misma VM. Para que sirva de verdad, copialo fuera:
    scp usuario@vm:~/freqtrade-backups/*.tar.gz .
EOF
