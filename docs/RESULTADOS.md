# Resultados

Registro de lo que se ha medido, en orden. Es el documento que responde a la
pregunta del proyecto: **¿existe una ventaja real después de comisiones?**

Dos estrategias medidas. La primera no tiene ventaja. La segunda sí tiene una
ventaja medible, pero **no supera a comprar y mantener**.

| | TrendPullbackV1 | TrendRiderV1 |
|---|---|---|
| Idea | Reversión a la media | Seguimiento de tendencia |
| Timeframe | 1h (filtro 4h) | 4h (filtro diario) |
| Pares | 2 | 6 |
| Periodo in-sample | 2023-02 → 2025-01 | 2019-09 → 2025-01 |
| Operaciones | 101 | **194** |
| Duración media | 14 horas | **15 días** |
| Profit | **−4,84%** | **+200,70%** |
| Max drawdown | 8,3% | 22,5% |
| Semáforo | 2 PASA / 7 FALLA | **6 PASA / 2 REVISAR / 1 FALLA** |
| Veredicto | Sin ventaja | Ventaja real, pierde contra buy & hold |

Informes completos: [report.html](report.html) · [report-trendrider.html](report-trendrider.html)

---

## Prueba hacia adelante en curso

El histórico ya está gastado: 2025-2026 se usó como out-of-sample, así que
cualquier estrategia ajustada ahora mirando ese periodo estaría sobreajustada.
La única validación honesta que queda es medir hacia adelante.

| | |
|---|---|
| Inicio | **2026-10-20** |
| Revisión | **~2027-01-20** (3 meses) |
| Estrategia | TrendRiderV1, **sin modificar** |
| Modo | dry-run: precios en vivo de la API pública de Binance, órdenes simuladas |
| Capital simulado | 40 USDT |
| Base de datos | `user_data/tradesv3.trendrider.dryrun.sqlite` (local, no versionada) |

Reglas:

1. No se toca la estrategia durante la prueba.
2. Criterio de éxito fijado de antemano: valor esperado por operación > 0 con
   un número suficiente de operaciones. Si no, se cierra el proyecto.
3. Es normal que pase días sin operar: solo entra con tendencia diaria alcista
   y ruptura de máximos.

---

## Veredicto final: no pasa a dinero real

Out-of-sample de TrendRiderV1 (2025-01-01 → 2026-10-20), medido **una sola
vez**, tras corregir el riesgo con dimensionado al 2% por operación:

| | In-sample | Out-of-sample |
|---|---|---|
| Operaciones | 186 | 44 (umbral 50) |
| Profit total | +192,43% | **−11,39%** |
| EV por operación | +0,4138 USDT | **−0,1036 USDT** |
| Win rate | 43,5% | 38,6% |
| Max drawdown | 16,91% | 15,90% |
| BTC en el periodo | +811,2% | −13,1% |
| Semáforo | 9 PASA | **2 PASA / 1 REVISAR / 6 FALLA** |

El win rate solo cayó 4,9 puntos: la señal no se degradó. Lo que se derrumbó
fue el tamaño de las ganancias (+5,64% → −1,68% por operación). Sin tendencia,
las ganadoras dejan de correr. **La estrategia no tiene ventaja independiente
del régimen**; el +192% del in-sample era en buena parte el mercado alcista.

Perdió menos que comprar y mantener (−11,39% vs −13,07%) con un tercio del
drawdown, pero perder menos que un benchmark que pierde no es una ventaja.

Informe: [report-trendrider-oos.html](report-trendrider-oos.html)

---

## TrendRiderV1 — ventaja medible que no justifica el riesgo

In-sample **2019-09-08 → 2025-01-01**, 6 pares en 4h, datos reales de Binance.

| Criterio | Valor | Umbral | |
|---|---|---|---|
| Nº de operaciones | 194 | ≥ 100 | PASA |
| Valor esperado por operación | +0,4138 USDT | > 0 | PASA |
| Profit factor | 1,82 | > 1,3 | PASA |
| Max drawdown | 22,5% | < 20% | REVISAR |
| Sharpe | 0,98 | > 0,5 | PASA |
| Sortino | 0,68 | > 0,8 | REVISAR |
| Aguanta sin el mejor mes (2021-02) | +58,90 USDT | > 0 | PASA |
| Aguanta sin la mejor operación | +66,55 USDT | > 0 | PASA |
| **Supera a comprar y mantener** | **+200,7% vs +811,2%** | profit o ratio | **FALLA** |

### La comparación que decide

| | TrendRiderV1 | Buy & hold BTC |
|---|---|---|
| Profit total | +200,7% | **+811,2%** |
| CAGR | 23,0% | **51,5%** |
| Max drawdown | **22,5%** | 76,6% |
| **Profit / drawdown** | 8,93 | **10,59** |
| Tiempo expuesto | parcial | 100% |

El drawdown de BTC está medido **sobre el precio diario**, no sobre las
operaciones: con una sola operación abierta, el drawdown calculado desde
cierres es 0% por construcción. El fondo real fue el 2022-11-21.

La estrategia gana claramente en riesgo —22,5% frente a 76,6%— pero pierde en
profit por un factor de 4 y **también pierde en el ratio profit/drawdown**. Por
la regla del proyecto eso es un FALLA: una estrategia que no supera al
benchmark ni en profit ni en profit/drawdown no justifica el riesgo operativo,
la infraestructura ni el tiempo.

Hay un matiz que la regla no captura: un drawdown del 76,6% es soportable en
una hoja de cálculo y casi nadie lo soporta con dinero real. Pero eso es un
argumento sobre el comportamiento humano, no una ventaja medida.

### Lo que sí quedó demostrado: el problema del coste se resuelve

| | TrendPullbackV1 | TrendRiderV1 |
|---|---|---|
| Duración media | 14 horas | 15 días |
| Ventaja BRUTA por operación | +0,008% | **+5,38%** |
| Coste de transacción | 0,200% | 0,200% |
| **Coste / ventaja** | **24,05x** | **0,04x** |

Con dos puntos de medición, la lección queda establecida:

> Con comisiones del 0,2% ida y vuelta, la frecuencia de operación determina si
> la ventaja necesaria es alcanzable. No es un detalle de implementación: es la
> restricción que gobierna el diseño.

### Auditoría anti-sesgo

| Prueba | Resultado |
|---|---|
| `lookahead-analysis` de Freqtrade | **No concluyente** — "too few trades caught" incluso con 194 operaciones y `--targeted-trade-amount 120`. Recorta el periodo y `startup_candle_count = 1500` se come la ventana |
| **`bias_check.py`** (truncamiento) | **Sin sesgo** — 6 pares × 14 indicadores × 8 cortes |
| **Control negativo** | **Detecta el sesgo** — un `shift(-1)` deliberado cazado en 8/8 cortes |
| `recursive-analysis` | **PASA** — `ema200_1d` converge a 0,000% en 1500 velas |

`scripts/bias_check.py` se escribió porque la herramienta de Freqtrade no puede
auditar esta estrategia, y quedarse sin auditoría no era opción. Hace la
comprobación que *es* la definición de lookahead: calcula los indicadores con
la serie completa, los recalcula con la serie **cortada** en el instante *t*, y
exige que el valor en *t* sea idéntico. Si cambia, el cálculo original usaba
datos posteriores.

El detalle que la hace válida: corta **también la serie diaria**. La primera
versión solo truncaba las velas de 4h, y la estrategia pedía el diario al
`DataProvider`, que le devolvía el histórico completo. Esa versión habría dado
OK sin probar nada. Por eso el control negativo no es opcional: **una prueba
que no puede fallar no es una prueba.**

No cubre `custom_stoploss` ni la simulación de órdenes.

### Riesgo que hay que arreglar antes de cualquier dry-run

Ocho operaciones perdieron el 24% cada una:

| Motivo de salida | Salidas | Profit medio | Total |
|---|---|---|---|
| `trailing_stop_loss` | 184 | +6,56% | +240,5% |
| **`stop_loss`** (tope del 25%) | **8** | **−24,23%** | **−38,3%** |
| `force_exit` | 2 | −3,83% | −1,5% |

Esas 8 operaciones se comieron 15,3 USDT: el 38% de una cuenta de 40. El
`STOP_CAP = 0.25` es demasiado ancho para este capital. Con 4 posiciones
abiertas, un racimo de esos stops en la misma semana haría mucho daño. Es un
parámetro de **riesgo**, no de rentabilidad: hay que estrecharlo por
supervivencia, no por optimizar el backtest.

### Grados de libertad consumidos

| # | Decisión | Sobre qué | Coste |
|---|---|---|---|
| 1 | Escala temporal del stop: ATR de 4h → ATR diario | Medición del ATR, no de rentabilidad | Bajo |

Una sola decisión, tomada midiendo que 3×ATR de 4h da un stop del 4,6% que se
toca en horas, frente al 12% del ATR diario. No se probaron valores buscando
el mejor resultado.

`hyperopt` nunca se corrió. Los parámetros siguen en sus valores de diseño
(`breakout_window=30`, `atr_mult=3.0`, `min_atr_pct=0.010`).

### El periodo in-sample fue excepcionalmente favorable

2019-09 → 2025-01 contiene dos mercados alcistas enormes. BTC pasó de ~$10.400
a ~$94.000. El "Market change" medio de los 6 pares fue **+2.395%**. Cualquier
estrategia long-only va a parecer buena ahí, y el +200,7% está muy por debajo
de la media del mercado.

**El out-of-sample 2025-01 → hoy es, en cambio, bajista: BTC −13,4% con un 53%
de drawdown.** Eso lo convierte en la prueba ideal de la hipótesis que el
in-sample no puede responder: ¿el filtro de tendencia diaria mantiene la
estrategia fuera del mercado cuando no hay tendencia?

Medir el precio de BTC en ese periodo no consume el out-of-sample. Correr la
estrategia sobre él, sí. Sigue sin usarse.

---

## Tres fallos silenciosos que produjeron números creíbles y falsos

Es el hallazgo más transferible del proyecto. Ninguno dio error: todos dieron
resultados.

### 1. `config.json` sobreescribió el timeframe de la estrategia

`TrendRiderV1` declara `timeframe = "4h"`. `config.json` fija `"timeframe": "1h"`
para la otra estrategia, y **el config gana**. La estrategia corrió en velas de
1h, con 2 pares en vez de 6 (los únicos con datos de 1h) y 22 meses en vez de
63 — y produjo una tabla perfectamente plausible: 25 operaciones, +5,77%. Sin
mirar la fecha de la primera operación, esos números habrían pasado por
válidos.

**Regla:** verificar la línea `Backtested X -> Y` del encabezado antes de leer
cualquier métrica. Si la estrategia declara un timeframe distinto al del
config, usar un overlay (`-c base.json -c overlay.json`) o `--timeframe`.

### 2. El Sharpe estaba inflado 4x

`report.py` construía la serie de retornos diarios **solo con los días que
tenían cierre de operación** y la anualizaba con √365. Con 194 operaciones en
1927 días, solo 126 días (7%) tenían cierre: el Sharpe salía **3,88** en vez
de **0,98**.

Un Sharpe de 3,88 describe una estrategia de primer nivel mundial. 0,98 es una
estrategia decente. La diferencia entre esos dos números es la diferencia
entre poner dinero y no ponerlo.

**Regla:** los días planos también son días. Diluyen la media y bajan el
ratio, que es exactamente lo que debe pasar en una estrategia de baja
frecuencia.

### 3. El benchmark podía ser de otro periodo

`report.py` busca el benchmark por nombre de estrategia y coge el más
reciente. Al medir `TrendPullbackV1` (2023-2024) agarró el buy & hold de
2019-2025 (+785%) en vez del de su propio periodo (+307%), y la tabla salía
creíble con los números equivocados.

**Corregido:** ahora compara los periodos y avisa si el desfase supera el 10%
del span, tanto en la terminal como dentro del informe. La comparación usa la
fecha de **apertura** de la primera operación, porque un buy & hold de una
sola operación tiene la misma fecha de apertura y cierre.

---

## TrendPullbackV1 — cómo se llegó al veredicto de "sin ventaja"

Tres fallos, cada uno descubierto solo al ejecutar el código. El orden importa:
cada corrección destapó el siguiente problema.

### 1. La entrada era casi imposible de satisfacer

Especificación original: *RSI(14) cruza al alza 35 **y** el cierre está sobre la
EMA50 de 1h*, en la misma vela.

| Condición | BTC | ETH |
|---|---|---|
| RSI(14) cruza al alza 35 | 815 veces | 818 veces |
| Cierre sobre EMA50 de 1h | 52,1% del tiempo | 50,6% |
| **Las dos a la vez** | **6 de 815** | **4 de 818** |

En el **99%** de los cruces de RSI, el cierre quedaba **bajo** la EMA50. Mediana
−1,34% (BTC), −1,74% (ETH); el máximo en 815 cruces fue +0,36%.

Es lógica, no mala suerte: que el RSI(14) baje a 35 **implica** un retroceso lo
bastante grande para perder la media de 50 periodos. Pedir las dos cosas a la vez
es pedir un retroceso que no retrocede.

**Resultado:** 3 operaciones en 23 meses. `lookahead-analysis` ni pudo correr
(*"found 1 trades which is less than minimum_trade_amount 10"*).

**Corrección:** separar las condiciones en el tiempo. Setup — el RSI tocó <35 en
las últimas 12 velas. Gatillo — el cierre cruza al alza la EMA50. Se entra en la
vuelta, no en la caída, que era la intención original.

Señales medidas en 2023-01 → 2026-10 (BTC+ETH):

| Variante | Señales | Por mes |
|---|---|---|
| Original — cruce RSI35 + close>EMA50 | 5 | 0,1 |
| Cruce RSI35 + EMA50 subiendo | 60 | 1,3 |
| **Setup + gatillo (adoptada)** | **237** | **5,2** |
| Cruce RSI35 + close>EMA200(1h) | 241 | 5,3 |
| Cruce RSI45 + close>EMA50 | 436 | 9,6 |

### 2. La salida se comía la entrada

Con la entrada corregida salieron 111 operaciones, pero:

| Motivo de salida | Salidas | Win rate | Profit |
|---|---|---|---|
| **`lost_ema50`** | **91** (82%) | **1,1%** | **−14,91%** |
| `rsi_overbought` | 11 | 100% | +5,47% |
| `roi` | 2 | 100% | +0,66% |
| `trailing_stop_loss` | 7 | 14,3% | −2,91% |
| `stop_loss` (ATR) | **0** | — | — |

Entrar **cuando** el cierre cruza al alza la EMA50 y salir **al perderla** es
entrar y salir en el mismo cruce. Y el stop por ATR nunca se disparó: esta salida
se le adelantaba siempre, así que toda la lógica de `custom_stoploss` quedaba sin
ejercitar.

Tres correcciones probadas en el mismo periodo:

| Variante | Operaciones | Profit | Win rate | Drawdown |
|---|---|---|---|---|
| Sin corregir | 111 | −11,69% | 13,5% | 11,69% |
| **A — quitar la regla (adoptada)** | 101 | **−4,84%** | 50,5% | 8,30% |
| B — colchón del 1% | 101 | −3,66% | 49,5% | 6,91% |
| C — salir por EMA200 de 1h | 102 | −5,69% | 46,1% | 7,54% |

Se adoptó **A**, que no es la mejor por una décima. B daba −3,66%. Pero las tres
pierden, y elegir la menos mala por un decimal del in-sample es exactamente el
ajuste que este proyecto intenta evitar. A tiene una razón detrás — la regla
contradice la entrada — y B tiene un número. Se prefiere la razón.

### 3. Tres errores de implementación que solo salen al ejecutar

- `config.json`: el schema de Freqtrade exige que `telegram.token` y `chat_id`
  **existan** aunque `enabled` sea `false`. En Docker funcionaba porque
  `env_file` los inyectaba.
- `freqtrade.vendor.qtpylib` está deprecado → `from technical import qtpylib`.
- `lookahead-analysis` **no acepta** `--cache none`.

---

### Grados de libertad consumidos (TrendPullbackV1)

Llevar la cuenta es lo que separa una validación de un ejercicio de confirmación.

| # | Decisión | Sobre qué datos | Coste |
|---|---|---|---|
| 1 | Regla de entrada: setup + gatillo | Solo **cuenta de señales**, ninguna rentabilidad | Bajo |
| 2 | Regla de salida: quitar `lost_ema50` | Rentabilidad in-sample, 3 variantes | Medio |

Dos decisiones sobre el in-sample. Si esto llegara a cinco o seis iteraciones, el
in-sample dejaría de significar nada y habría que empezar con datos nuevos.

Nunca se corrió `hyperopt`. Los parámetros siguen en sus valores de diseño
(`buy_rsi=35`, `sell_rsi=70`, `atr_mult=2.0`).

---

## Qué NO prueban estos resultados

- **No prueba que el trading sistemático no funcione.** Prueba que *esta* regla,
  en *estos* dos pares, en *este* timeframe, durante *este* periodo, no tiene
  ventaja medible.
- **No prueba que buy & hold sea mejor estrategia.** Prueba que fue mejor en un
  periodo que resultó ser muy alcista para BTC. En un mercado bajista de dos
  años, el +101% sería un −60%, y una estrategia que solo está dentro del mercado
  el 5% del tiempo se vería muy distinta.
- **No descarta los pares ni los indicadores.** Descarta esta combinación.

## Qué sí prueba

Que el proceso funciona. Se construyó una hipótesis, se implementó, se midió, y
la medición dijo que no. Eso es el resultado correcto de un experimento cuyo
objetivo era averiguarlo, no confirmarlo.

Y hay una lección transferible, que es el verdadero producto de este trabajo:

> Con comisiones del 0,2% ida y vuelta, una estrategia que opera cada 14 horas
> necesita una ventaja bruta superior al 0,2% por operación. Esa es una barra
> **alta** para una señal técnica de corto plazo. La frecuencia de operación no
> es un detalle de implementación: es lo que determina si la ventaja necesaria
> es alcanzable.

---

## Si se quiere seguir

El error a evitar es seguir retocando esta estrategia hasta que el backtest se
vea bien. Eso no encuentra ventaja, encuentra sobreajuste.

El problema real que los números señalan es **el coste por operación**, no el
umbral del RSI. Dos direcciones que atacan eso de raíz:

1. **Menos operaciones, objetivos más grandes.** Timeframe de 4h o diario, con
   objetivos del 5-15%. Si la operación busca un 10%, un 0,2% de coste es el 2%
   del objetivo en vez del 100%. Cambia la barra de "imposible" a "difícil".
2. **Reducir el coste.** BNB para descuento de comisión, órdenes limit tipo maker
   (0,075% en vez de 0,1%). Ayuda, pero con una ventaja bruta de 0,008% no
   alcanza ni de lejos: el problema es la señal, no solo el coste.

Cualquiera de las dos es **una estrategia nueva**, no un ajuste de esta. Merece
su propio archivo, su propio periodo de diseño, y este mismo proceso.
