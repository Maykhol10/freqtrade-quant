# Resultados

Registro de lo que se ha medido, en orden. Es el documento que responde a la
pregunta del proyecto: **¿existe una ventaja real después de comisiones?**

---

## Veredicto actual: NO hay ventaja

Medido el **2026-10-20**, con datos reales de Binance (33.327 velas de 1h por
par desde 2023-01-01), Freqtrade 2026.9.

### In-sample 2023-02-07 → 2025-01-01

| | TrendPullbackV1 | Buy & hold BTC |
|---|---|---|
| Operaciones | 101 | 2 |
| Win rate | 50,5% | 100% |
| **Profit total** | **−4,84%** (−1,936 USDT) | **+101,05%** (+40,42 USDT) |
| Max drawdown | 8,30% | 0,00% |
| Duración media | 14h18 | 693 días |

### La descomposición que cierra el caso

```
Profit NETO (lo que queda)         −1,936 USDT
Comisiones pagadas                 −2,020 USDT   (101 ops × 0,020)
Profit BRUTO (antes de comisión)   +0,084 USDT
                                   ───────────
Valor esperado BRUTO por operación  +0,008%
Coste de transacción por operación  −0,200%

La comisión es 24x la ventaja bruta de la señal.
```

**Esto no es "una ventaja pequeña que se la come la comisión".** Eso sería un
resultado interesante: significaría que hay señal y que el problema es el coste.
Lo que hay es otra cosa: +0,084 USDT brutos repartidos en 101 operaciones es
indistinguible de cero. La señal no predice nada.

Para ser rentable, la entrada necesitaría una ventaja bruta superior al **0,20%**
por operación. Tiene **0,008%**.

### No se ha mirado el out-of-sample, a propósito

2025-2026 sigue intacto. Mirarlo ahora sería quemar la única medición limpia que
queda para validar una estrategia que **ya falla en el periodo de diseño**. El
out-of-sample sirve para confirmar una ventaja encontrada in-sample, no para
buscar una segunda oportunidad.

---

## Cómo se llegó aquí

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

## Grados de libertad consumidos

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

## Qué NO prueba este resultado

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
