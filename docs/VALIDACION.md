# Plan de validación y plantilla de métricas

## Partición temporal

```
2023-01-01 ─────────────────────────────────────────────────────── 2026-10-20
│                                                                          │
├── 2023-01-01 → 2023-02-15 ── CALENTAMIENTO (900 velas de 1h)
│                              No se opera. Solo alimenta las EMA.
│
├── 2023-02-15 → 2024-12-31 ── IN-SAMPLE (diseño)
│                              Aquí se decide todo: umbrales, ATR, ROI.
│                              Hyperopt, si se usa, vive solo aquí.
│
└── 2025-01-01 → hoy ───────── OUT-OF-SAMPLE (validación)
                               SE MIRA UNA VEZ. Lo que salga, sale.
```

**La regla que hace que esto valga algo:** cada vez que mires el out-of-sample y
luego ajustes algo, el out-of-sample se convierte en in-sample y pierdes tu única
medición honesta. No hay forma de recuperarla. Si necesitas varias iteraciones,
córtale un tercer trozo al in-sample y usa ese como validación intermedia.

---

## Plantilla de reporte

Rellenar una copia de esta tabla por cada prueba. Sin esto no hay comparación
posible, solo impresiones.

### Prueba: `__________`  ·  Periodo: `__________`  ·  Fee: `__________`

| Métrica | Valor | Umbral | ¿Pasa? |
|---|---|---|---|
| **Nº de operaciones** | | ≥ 100 (in-sample) / ≥ 50 (OOS) | |
| Win rate | | — (informativo) | |
| Ganancia media por op ganadora | | — | |
| Pérdida media por op perdedora | | — | |
| **Valor esperado por op (post-comisiones)** | | **> 0** | |
| Profit total % | | > B&H o mejor ratio | |
| Profit total USDT | | — | |
| **Profit factor** | | > 1.3 | |
| **Max drawdown %** | | < 20% | |
| **Sharpe** | | > 0.5 | |
| **Sortino** | | > 0.8 | |
| CAGR % | | — | |
| Duración media de operación | | — | |
| Mejor mes / peor mes | | — | |
| Market change % (el mercado) | | — | |

### Comparación obligatoria contra buy & hold

| | TrendPullbackV1 | BuyAndHoldBTC | Veredicto |
|---|---|---|---|
| Profit total % | | | |
| Max drawdown % | | | |
| Sharpe | | | |
| **Profit / Drawdown** | | | |
| Tiempo expuesto al mercado % | | 100% | |

---

## Cómo leer cada métrica (y cómo no engañarse)

### Valor esperado por operación

Es **la única** métrica que decide si existe una ventaja:

```
EV = (win_rate × ganancia_media) − ((1 − win_rate) × pérdida_media) − comisiones
```

Con comisión de 0.1% por lado, cada operación de 10 USDT paga ~0.02 USDT de ida
y vuelta. Si el EV es +0.03 USDT por operación, la ventaja es real pero diminuta:
el 40% de tu ganancia bruta se la lleva Binance. Si el EV es negativo, no hay
nada que discutir, independientemente de lo bonita que sea la curva de equity.

### Win rate — la métrica más engañosa

Un win rate del 80% con pérdidas 5 veces mayores que las ganancias es una
estrategia perdedora. El ROI escalonado de esta estrategia (`minimal_roi`) infla
el win rate artificialmente: cierra muchas operaciones pequeñas en verde y deja
que las malas corran hasta el stop. **Nunca mires el win rate sin la pérdida
media al lado.**

### Profit factor

`ganancias brutas / pérdidas brutas`. Por debajo de 1.0 pierde dinero. Entre 1.0
y 1.3, la ventaja no sobrevive al slippage. Por encima de 2.0 en cripto con una
estrategia de 3 parámetros: sospecha sobreajuste o lookahead antes de celebrar.

### Max drawdown

Lo que de verdad determina si puedes operar el sistema. Un drawdown del 30% en
backtest se siente como un 60% cuando es tu dinero y llevas 3 semanas en rojo.
Con 40 USDT da igual en términos absolutos; lo que estás validando es si
**serías capaz de no apagar el bot** en el peor momento.

### Sharpe y Sortino

Sharpe penaliza toda la volatilidad; Sortino solo la volatilidad a la baja. Para
una estrategia direccional long-only, **Sortino es más informativo**: no te
castiga por subir rápido. Si Sharpe es alto pero Sortino bajo, hay caídas
bruscas concentradas.

### Nº de operaciones — el filtro previo a todo lo demás

Con menos de 100 operaciones, el intervalo de confianza del win rate es tan
ancho que cualquier conclusión es fe, no estadística. Orden de magnitud: con 30
operaciones, un win rate observado del 60% es compatible con un verdadero 42-76%.
No puedes distinguir una estrategia buena de una mala.

**Si salen < 100 operaciones, las salidas válidas son:**
1. Añadir pares (SOL/USDT, BNB/USDT, XRP/USDT) — más muestra, misma lógica.
2. Bajar el timeframe base a 30m o 15m manteniendo el filtro de 4h.
3. Aceptar que no se puede concluir y no pasar a real.

**La salida inválida** —y la tentación permanente— es relajar el filtro de
tendencia para generar más señales. Eso no aumenta la muestra: cambia la
estrategia y te devuelve al punto de partida con un backtest ya contaminado.

---

## Registro de pruebas

Llevar aquí el historial. La fecha importa: deja constancia de en qué orden
miraste cada cosa, que es lo que distingue una validación de un ejercicio de
confirmación.

| Fecha | Prueba | Periodo | Fee | Ops | EV/op | Profit % | DD % | Sharpe | Nota |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |
| | | | | | | | | | |
| | | | | | | | | | |
