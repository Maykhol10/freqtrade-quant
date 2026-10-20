# Comandos exactos

Todos los comandos se ejecutan desde la raíz del proyecto en el servidor Linux.
`docker compose run --rm freqtrade <subcomando>` crea un contenedor efímero que
comparte el volumen `user_data`, así que los datos y resultados persisten.

```bash
cd /opt/freqtrade-quant
alias ft='docker compose run --rm freqtrade'   # atajo para esta sesión
```

---

## 0. Preparación del servidor (una vez)

```bash
# Docker + compose plugin
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git jq curl
sudo usermod -aG docker $USER && newgrp docker

# Proyecto
sudo mkdir -p /opt/freqtrade-quant && sudo chown -R $USER:$USER /opt/freqtrade-quant
cd /opt/freqtrade-quant
git clone https://github.com/Maykhol10/freqtrade-quant.git .

# Secretos
cp .env.example .env
chmod 600 .env
nano .env                       # rellenar token de Telegram, chat_id, password API

# El contenedor corre como uid 1000
sudo chown -R 1000:1000 user_data

# Descargar la imagen
docker compose pull
docker compose run --rm freqtrade --version
```

---

## 1. Descarga de datos

```bash
# Serie principal: 1h y 4h, ambos pares, desde 2023-01-01 hasta hoy
ft download-data \
  --config user_data/config.json \
  --exchange binance \
  --trading-mode spot \
  --pairs BTC/USDT ETH/USDT \
  --timeframes 1h 4h \
  --timerange 20230101-

# Verificar qué quedó descargado (fechas reales, huecos, nº de velas)
ft list-data --config user_data/config.json --show-timerange
```

> **Nota sobre `startup_candle_count = 900`.** El backtest consume 900 velas de 1h
> (~37 días) solo para calentar las EMA. Si pides `--timerange 20230101-...`,
> Freqtrade retrocede automáticamente para alimentar el calentamiento, pero
> necesita que esos datos existan. Por eso descargamos desde 2023-01-01 aunque
> el primer backtest empiece en 2023-02-15.

### Opcional pero recomendado: velas de 5m para `--timeframe-detail`

Sin esto, el backtest asume que dentro de una vela de 1h el precio toca primero
el objetivo y luego el stop (o al revés) según un orden fijo. Con detalle de 5m
la simulación de stops y trailing es mucho más honesta.

```bash
ft download-data \
  --config user_data/config.json --exchange binance --trading-mode spot \
  --pairs BTC/USDT ETH/USDT --timeframes 5m --timerange 20230101-
```

---

## 2. Auditoría anti-sesgo (ANTES de mirar un solo resultado)

Este paso no es opcional. Un backtest con lookahead puede mostrar un 300% anual
que en real es -40%.

```bash
# 2a. ¿La estrategia lee el futuro?
ft lookahead-analysis \
  --config user_data/config.json \
  --strategy TrendPullbackV1 \
  --timerange 20230201-20250101 \
  --cache none
```

**Interpretación:** la tabla final debe decir `biased_entry: False` y
`biased_exit: False` para cada indicador. Si alguno sale `True`, la estrategia
está rota y **no se sigue adelante**. Causa típica: usar `.shift(-1)`, `max()` /
`min()` sobre toda la serie, o leer una informative sin `merge_informative_pair`.

```bash
# 2b. ¿Los indicadores cambian de valor según cuántas velas de calentamiento haya?
ft recursive-analysis \
  --config user_data/config.json \
  --strategy TrendPullbackV1 \
  --timerange 20230201-20250101 \
  --startup-candle 199 399 799 999
```

**Interpretación:** busca la columna de diferencia porcentual por indicador.
`ema200_4h` y `rsi` deberían converger a ~0% al llegar a 799/999 velas. Si a
900 velas todavía hay desvío >0.1%, sube `startup_candle_count` en la estrategia
y repite. Esto es *recursive bias*: no es trampa, pero hace que el backtest y el
dry-run calculen cosas distintas.

---

## 3. Backtest in-sample (diseño): 2023-01 → 2024-12

```bash
ft backtesting \
  --config user_data/config.json \
  --strategy TrendPullbackV1 \
  --timerange 20230201-20250101 \
  --timeframe-detail 5m \
  --breakdown month \
  --enable-protections \
  --cache none \
  --export trades \
  --export-filename user_data/backtest_results/in_sample.json
```

Flags que importan y por qué:

| Flag | Razón |
|---|---|
| `--timeframe-detail 5m` | Simula stops dentro de la vela de 1h. Sin esto los stops por ATR salen optimistas. |
| `--enable-protections` | Sin esto `StoplossGuard` / `MaxDrawdown` no se aplican y el backtest no refleja el bot real. |
| `--cache none` | Evita que te devuelva un resultado viejo tras editar la estrategia. Error clásico. |
| `--breakdown month` | Revela si la ganancia viene de 2 meses buenos y 10 planos. |
| `--export trades` | Necesario para `backtesting-analysis`. |

### Desglose por razón de salida

```bash
ft backtesting-analysis \
  --config user_data/config.json \
  --analysis-groups 0 1 2 \
  --indicators rsi atr_pct uptrend_4h
```

Pregunta clave: ¿de dónde sale el dinero? Si el 90% del profit viene de
`exit_tag = roi` y los `lost_ema50` son todos pérdidas, la señal de salida no
aporta y la estrategia es en realidad "comprar y esperar el ROI".

---

## 4. Prueba de estrés de comisiones y slippage

Freqtrade **no simula slippage**: asume llenado al precio de la vela. La forma
seria de acotarlo es repetir el backtest con comisiones infladas, que es lo
mismo que un slippage constante.

```bash
for FEE in 0.001 0.0015 0.002; do
  echo "===== fee = $FEE por lado ====="
  ft backtesting \
    --config user_data/config.json \
    --strategy TrendPullbackV1 \
    --timerange 20230201-20250101 \
    --timeframe-detail 5m --enable-protections --cache none \
    --fee $FEE 2>/dev/null | grep -E 'TOTAL|Total profit|Sharpe|Sortino|Max % of account|profit factor'
done
```

**Criterio:** si la ventaja desaparece a `0.0015` (0.3% ida y vuelta), no hay
ventaja. Está dentro del costo de transacción y lo que viste a `0.001` era ruido.
Con operaciones de 10 USDT en Binance spot, 0.2% round-trip son 0.02 USDT por
operación: la ganancia media por trade tiene que ser cómodamente superior a eso.

---

## 5. Benchmark: comprar y mantener BTC

```bash
ft backtesting \
  --config user_data/config.json \
  --strategy BuyAndHoldBTC \
  --pairs BTC/USDT \
  --max-open-trades 1 \
  --stake-amount unlimited \
  --timerange 20230201-20250101 \
  --cache none
```

Compara tres cosas, no solo el profit:

| Métrica | TrendPullbackV1 | BuyAndHoldBTC |
|---|---|---|
| Profit total % | | |
| Max drawdown % | | |
| Sharpe | | |
| **Profit / Drawdown** | | |

Si B&H gana en profit **y** en drawdown, la estrategia no tiene razón de existir.
Si la estrategia gana menos profit pero con la mitad del drawdown, sí la tiene:
puedes apalancar la exposición y llegar al mismo retorno con menos riesgo.

---

## 6. Hyperopt (opcional) — leer la advertencia

> **Riesgo de sobreajuste.** Hyperopt busca los parámetros que mejor explican el
> pasado, no los que mejor predicen el futuro. Con 3 parámetros y ~200
> operaciones, el riesgo ya es real. Con 6+ parámetros es garantía de autoengaño.
>
> Reglas que no se rompen:
> 1. Hyperopt **solo** en 2023-02 → 2024-12. Nunca sobre 2025-2026.
> 2. Si el mejor resultado es mucho mejor que el default, sospecha, no celebres.
> 3. Mirar la nube de resultados: si los top-10 epochs tienen parámetros muy
>    distintos entre sí, no hay señal, hay ruido.
> 4. `SharpeHyperOptLossDaily` penaliza la volatilidad del retorno. Optimizar
>    profit puro produce estrategias con drawdowns insoportables.

```bash
ft hyperopt \
  --config user_data/config.json \
  --strategy TrendPullbackV1 \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy sell \
  --epochs 150 \
  --timerange 20230201-20250101 \
  --timeframe-detail 5m \
  --enable-protections \
  --min-trades 100 \
  -j 2

# Ver los mejores epochs y su dispersión
ft hyperopt-list --config user_data/config.json --profitable --print-json | head -40

# Aplicar un resultado (genera TrendPullbackV1.json junto a la estrategia)
ft hyperopt-show --config user_data/config.json --index 1 --print-json
```

`--min-trades 100` descarta automáticamente los epochs sin significancia
estadística. `-j 2` limita a 2 núcleos: una VM pequeña de Azure se congela con
más.

---

## 7. Validación out-of-sample (la prueba de verdad): 2025-01 → hoy

**En este punto ya no se toca ningún parámetro.** Lo que salga, sale.

```bash
ft backtesting \
  --config user_data/config.json \
  --strategy TrendPullbackV1 \
  --timerange 20250101- \
  --timeframe-detail 5m \
  --breakdown month \
  --enable-protections \
  --cache none \
  --export trades \
  --export-filename user_data/backtest_results/out_of_sample.json

# El mismo periodo para el benchmark
ft backtesting --config user_data/config.json --strategy BuyAndHoldBTC \
  --pairs BTC/USDT --max-open-trades 1 --stake-amount unlimited \
  --timerange 20250101- --cache none
```

### Walk-forward por ventanas (más robusto que un solo corte)

```bash
for R in 20230201-20230801 20230801-20240201 20240201-20240801 \
         20240801-20250201 20250201-20250801 20250801-; do
  echo "########## $R ##########"
  ft backtesting --config user_data/config.json --strategy TrendPullbackV1 \
    --timerange $R --timeframe-detail 5m --enable-protections --cache none \
    2>/dev/null | grep -E 'Total/Daily Avg Trades|Total profit %|Max % of account|Sharpe|Sortino'
done
```

Lo que buscas no es que todas las ventanas sean positivas, sino **consistencia**:
una estrategia con +3%, +5%, -2%, +4%, +1% es infinitamente más confiable que
una con +40%, -15%, +2%, -8%, +1%, aunque la segunda sume más.

---

## 8. Gráficos

```bash
ft plot-dataframe --config user_data/config.json --strategy TrendPullbackV1 \
  --pairs BTC/USDT --timerange 20250101-20250401 --indicators1 ema50 \
  --indicators2 rsi

ft plot-profit --config user_data/config.json --strategy TrendPullbackV1 \
  --pairs BTC/USDT ETH/USDT --timerange 20250101-
```

Salida en `user_data/plot/*.html`. Pásalos a tu PC con
`scp usuario@vm:/opt/freqtrade-quant/user_data/plot/*.html .`

---

## 9. Lanzar el dry-run

```bash
# Comprobar config antes de arrancar
ft show-config --config user_data/config.json

docker compose up -d
docker compose logs -f --tail 50
```

En Telegram deberías recibir el mensaje de arranque. Comandos útiles del bot:
`/status`, `/profit`, `/daily 7`, `/performance`, `/balance`, `/stats`,
`/forceexit <id>`, `/stopentry`, `/reload_config`.

### FreqUI (opcional)

La API está cerrada a `127.0.0.1`. Desde tu PC:

```bash
ssh -L 8080:127.0.0.1:8080 usuario@tu-vm-azure
# abrir http://localhost:8080 en el navegador
```

### Resumen diario automático por Telegram

```bash
chmod +x scripts/daily_report.sh
./scripts/daily_report.sh            # probar a mano primero

crontab -e
# 21:00 hora de Lima, todos los días
0 21 * * * cd /opt/freqtrade-quant && ./scripts/daily_report.sh >> user_data/logs/daily_report.log 2>&1
```

---

## 10. Mantenimiento

```bash
# Actualizar datos (incremental, no re-descarga todo)
ft download-data --config user_data/config.json --exchange binance \
  --trading-mode spot --pairs BTC/USDT ETH/USDT --timeframes 1h 4h 5m --days 30

# Actualizar la imagen de Freqtrade
docker compose down && docker compose pull && docker compose up -d

# Reiniciar el dry-run desde cero (borra el historial simulado)
docker compose down
rm user_data/tradesv3.dryrun.sqlite
docker compose up -d
```
