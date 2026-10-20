---
title: freqtrade-quant
---

# freqtrade-quant

Validación cuantitativa de una estrategia de trading cripto en [Freqtrade](https://www.freqtrade.io/).
Binance **spot**, solo largos, sin apalancamiento.

> **Estado: boceto. Ninguna métrica medida todavía.**
> Nada de este proyecto debe operar con dinero real hasta completar la
> [checklist](CHECKLIST_REAL.md) completa.

[Código fuente en GitHub](https://github.com/Maykhol10/freqtrade-quant){: .btn }

---

## Qué es esto

Un experimento con un resultado posible y perfectamente aceptable: *"no hay
ventaja, no se opera"*.

El objetivo no es ganar dinero rápido, es **determinar con matemáticas si existe
una ventaja real después de comisiones**. Capital previsto en real: ~S/ 150
(~40 USDT), una escala donde el P/L es ruido estadístico y lo único que se
construye de verdad es el proceso.

---

## Documentación

| Documento | Para qué |
|---|---|
| **[SERVIDOR.md](SERVIDOR.md)** | Desplegar en una VM de Azure: tamaño, firewall, swap, systemd, diagnóstico |
| **[COMANDOS.md](COMANDOS.md)** | Los 10 pasos con comandos literales: datos, auditoría, backtest, dry-run |
| **[VALIDACION.md](VALIDACION.md)** | Partición temporal, plantilla de métricas y cómo no engañarse leyéndolas |
| **[CHECKLIST_REAL.md](CHECKLIST_REAL.md)** | Las 5 condiciones que deben cumplirse antes de usar dinero real |

### Dashboard de análisis

El informe con las métricas, la curva de capital, el drawdown, el desglose
mensual y el semáforo contra los umbrales se genera desde los resultados del
backtest:

```bash
make backtest-in && make benchmark-in
make dashboard          # -> docs/report.html
```

Aparecerá en `report.html` junto a esta página. **Todavía no existe: ningún
backtest se ha ejecutado.** El generador es
[`scripts/report.py`](https://github.com/Maykhol10/freqtrade-quant/blob/main/scripts/report.py),
solo librería estándar de Python, y devuelve código de salida 1 si algún
criterio bloqueante falla — así que sirve tal cual en un script o en CI.

---

## La estrategia en una frase

Comprar retrocesos de corto plazo **solo cuando la estructura de 4h es
alcista**, salir por sobrecompra o pérdida de la media, con stop dimensionado
por volatilidad real (ATR).

| | |
|---|---|
| Pares | BTC/USDT, ETH/USDT |
| Timeframe | 1h, con filtro de tendencia en 4h (informative pairs) |
| Filtro de tendencia | 4h: EMA50 > EMA200 **y** close > EMA200 |
| Entrada | 1h: RSI(14) cruza al alza 35 **y** close > EMA50 |
| Salida | RSI > 70 · close < EMA50 · ROI · stop |
| Stop | ATR(14) × 2 desde la entrada, acotado entre −1.5% y −5% |
| Trailing | Se activa en +3%, bloquea ~+1% |
| Posiciones | 3 simultáneas, 10 USDT cada una |
| Protecciones | CooldownPeriod · StoplossGuard · MaxDrawdown (25%) |

---

## El flujo de validación

```
1. Descargar datos        2023-01-01 → hoy, 1h + 4h (+ 5m para detalle)
2. Auditar sesgos         lookahead-analysis · recursive-analysis   ← bloqueante
3. Backtest in-sample     2023-02 → 2024-12
4. Estrés de comisiones   fee 0.1% / 0.15% / 0.2%                   ← bloqueante
5. Benchmark              comprar y mantener BTC, mismo periodo
6. (opcional) Hyperopt    solo in-sample, 3 parámetros, min-trades 100
7. Out-of-sample          2025-01 → hoy, UNA sola vez, sin tocar nada
8. Walk-forward           6 ventanas semestrales, buscar consistencia
9. Dry-run                3-4 semanas sin tocar nada
10. Checklist             completa, o no se pasa a real
```

Los dos pasos marcados como bloqueantes lo son de verdad. Un backtest con
lookahead puede mostrar un 300% anual que en real es −40%, y una ventaja que
desaparece al 0.15% por lado nunca fue una ventaja: era ruido dentro del costo
de transacción.

---

## Advertencias que conviene no olvidar

1. **Freqtrade no simula slippage.** Asume llenado al precio de la vela. El
   backtest es siempre optimista; el estrés de comisiones acota cuánto.
2. **Un backtest validado no predice el futuro.** Mide que hubo una ventaja en
   el pasado y que la implementación es correcta. Son dos cosas valiosas y
   ninguna es una garantía.
3. **Riesgo de muestra pequeña.** Dos pares en 1h con un filtro restrictivo
   pueden dar menos de 100 operaciones en 3 años. Si pasa, no hay conclusión
   posible — las salidas válidas están en [VALIDACION.md](VALIDACION.md).
4. **El dinero puede perderse completo.**

---

<small>
Este sitio es documentación de un proyecto personal de investigación. No es
asesoría financiera ni una recomendación de inversión. El trading de
criptomonedas puede resultar en la pérdida total del capital.
</small>
