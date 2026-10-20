# freqtrade-quant

Validación cuantitativa de una estrategia de trading cripto en Freqtrade.
Binance **spot**, solo largos, sin apalancamiento.

**Estado: boceto. Ninguna métrica medida todavía.** Nada de este repositorio
debe operar con dinero real hasta completar [`docs/CHECKLIST_REAL.md`](docs/CHECKLIST_REAL.md).

---

## Objetivo

Determinar con matemáticas **si existe una ventaja real después de comisiones**.
No es un proyecto para ganar dinero rápido: es un experimento con un resultado
posible y perfectamente aceptable — *"no hay ventaja, no se opera"*.

Capital previsto en real: **~S/ 150 (~40 USDT)**. A esa escala el P/L es ruido;
lo que se está construyendo es el proceso.

---

## Estructura

```
freqtrade-quant/
├── docker-compose.yml           Servicio del bot (dry-run, API en loopback)
├── Makefile                     Atajos de todo: make help
├── .env.example                 Plantilla de secretos -> copiar a .env
├── .gitignore / .gitattributes  Bloquea .env · fuerza LF para Linux
├── docs/
│   ├── SERVIDOR.md              Despliegue en Azure, firewall, diagnóstico
│   ├── COMANDOS.md              Comandos exactos, paso a paso
│   ├── VALIDACION.md            Partición temporal + plantilla de métricas
│   └── CHECKLIST_REAL.md        Qué debe cumplirse antes de usar dinero real
├── scripts/
│   ├── install.sh               Bootstrap idempotente del servidor
│   ├── preflight.sh             12 comprobaciones antes de arrancar
│   ├── daily_report.sh          Resumen diario a Telegram
│   ├── watchdog.sh              Vigilancia cada 15 min + alertas
│   ├── backup.sh                Respaldo rotativo de db y config
│   └── cron-install.sh          Instala las tareas programadas
├── systemd/
│   └── freqtrade-quant.service  Unidad systemd (opcional)
└── user_data/
    ├── config.json              Config de Freqtrade (dry_run: true)
    └── strategies/
        ├── TrendPullbackV1.py   La estrategia
        └── BuyAndHoldBTC.py     Benchmark obligatorio
```

---

## La estrategia en una frase

Comprar retrocesos de corto plazo **solo cuando la estructura de 4h es
alcista**, salir por sobrecompra o pérdida de la media, con stop dimensionado
por volatilidad real (ATR).

| | |
|---|---|
| Pares | BTC/USDT, ETH/USDT |
| Timeframe | 1h (filtro de tendencia en 4h vía informative pairs) |
| Filtro de tendencia | 4h: EMA50 > EMA200 **y** close > EMA200 |
| Entrada | 1h: **setup** RSI(14) tocó <35 en las últimas 12 velas · **gatillo** el cierre cruza al alza la EMA50 |
| Salida | RSI > 70 · close < EMA50 · ROI · stop |
| Stop | ATR(14) × 2 desde la entrada, acotado entre −1.5% y −5% |
| Trailing | Se activa en +3%, bloquea ~+1% |
| Posiciones | 3 simultáneas, 10 USDT cada una |
| Protecciones | CooldownPeriod · StoplossGuard · MaxDrawdown (25%) |

Detalle completo y razonamiento: [`user_data/strategies/TrendPullbackV1.py`](user_data/strategies/TrendPullbackV1.py)

---

## Decisiones de diseño que no son obvias

**El filtro de tendencia pide dos condiciones, no una.** `EMA50 > EMA200` tarda
semanas en invertirse tras un techo. Añadir `close > EMA200` corta la exposición
mucho antes y es lo que impide comprar retrocesos durante un mercado bajista,
que es donde mueren todas las estrategias de reversión a la media.

**La entrada usa un cruce, no un nivel.** `RSI < 35` compra durante toda la
caída. `crossed_above(RSI, 35)` espera a que el retroceso empiece a agotarse.
La diferencia en drawdown es grande.

**El trailing está dentro de `custom_stoploss`, no en `trailing_stop`.** Con
`use_custom_stoploss = True`, Freqtrade ignora los parámetros de trailing de la
clase. Tenerlos puestos daría una falsa sensación de que están activos. Aquí el
trailing es código explícito.

**El ATR se ancla a la vela de entrada.** Si el stop se recalculara con el ATR
actual, estaría usando información que no existía al abrir la operación. Se
localiza la vela exacta con `timeframe_to_prev_date()`.

**Solo 3 parámetros optimizables.** Con ~200 operaciones, optimizar más es
garantía de sobreajuste. Los límites del stop (−1.5% / −5%) **no** se optimizan:
son restricciones de riesgo, no parámetros a ajustar contra el historico.

---

## Flujo de trabajo

```
1. Descargar datos        2023-01-01 → hoy, 1h + 4h (+ 5m para detalle)
2. Auditar sesgos         lookahead-analysis · recursive-analysis   ← bloqueante
3. Backtest in-sample     2023-02 → 2024-12
4. Estrés de comisiones   fee 0.1% / 0.15% / 0.2%                   ← bloqueante
5. Benchmark              BuyAndHoldBTC, mismo periodo
6. (opcional) Hyperopt    solo in-sample, 3 parámetros, min-trades 100
7. Out-of-sample          2025-01 → hoy, UNA sola vez, sin tocar nada
8. Walk-forward           6 ventanas semestrales, buscar consistencia
9. Dry-run                3-4 semanas sin tocar nada
10. Checklist             docs/CHECKLIST_REAL.md completo, o no se pasa a real
```

Comandos literales: [`docs/COMANDOS.md`](docs/COMANDOS.md)

---

## Arranque rápido (en el servidor)

```bash
git clone https://github.com/Maykhol10/freqtrade-quant.git /opt/freqtrade-quant
cd /opt/freqtrade-quant

./scripts/install.sh      # Docker, .env con secretos generados, permisos, imagen
make download             # datos 1h + 4h desde 2023-01-01
make audit                # lookahead + recursive  <- BLOQUEANTE
make backtest-in
```

`install.sh` es idempotente y termina verificando que las estrategias **importan de
verdad** dentro de la imagen de Freqtrade, no solo que el archivo existe. No arranca
el bot ni descarga datos: esas decisiones siguen siendo tuyas.

Cuando decidas poner el dry-run en marcha:

```bash
make preflight       # 12 comprobaciones; no debe salir ninguna FALLA
make up
make cron-install    # resumen diario, vigilancia cada 15 min, respaldo semanal
```

Despliegue completo, tamaño de VM, reglas del NSG y tabla de diagnóstico:
[`docs/SERVIDOR.md`](docs/SERVIDOR.md). Todos los atajos: `make help`.

---

## Seguridad

- Las claves viven **solo** en `.env`, que está en `.gitignore`. Nunca en
  `config.json` ni en el código.
- Freqtrade lee los secretos por variables de entorno con el patrón
  `FREQTRADE__SECCION__CLAVE`, que sobreescriben `config.json`.
- La API key de Binance, cuando llegue el momento: **solo spot trading**, sin
  permiso de retiro, sin futuros, restringida a la IP de la VM.
- La API REST del bot está atada a `127.0.0.1:8080`. Acceso a FreqUI por túnel
  SSH: `ssh -L 8080:127.0.0.1:8080 usuario@vm`.

Antes de cada commit:

```bash
git check-ignore -v .env     # debe responder que está ignorado
git status                   # .env no debe aparecer ni como untracked
```

---

## Advertencias que conviene no olvidar

1. **Freqtrade no simula slippage.** Asume llenado al precio de la vela. El
   backtest es siempre optimista; el paso 4 acota cuánto.
2. **Un backtest validado no predice el futuro.** Mide que hubo una ventaja en
   el pasado y que la implementación es correcta. Son dos cosas valiosas y
   ninguna es una garantía.
3. **Riesgo de muestra pequeña.** Dos pares en 1h con un filtro restrictivo
   pueden dar < 100 operaciones en 3 años. Si pasa, no hay conclusión posible
   — ver las salidas válidas en [`docs/VALIDACION.md`](docs/VALIDACION.md).
4. **El dinero puede perderse completo.** 40 USDT es la cifra que debe poder
   desaparecer hoy sin afectar nada más.
