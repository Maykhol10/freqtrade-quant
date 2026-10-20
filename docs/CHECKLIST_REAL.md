# Checklist para pasar a dinero real

Capital previsto: **~S/ 150 (~40 USDT)**. Stake de 10 USDT, máximo 3 posiciones.

La regla que gobierna todo este documento: **cada casilla sin marcar es un
motivo suficiente para no pasar a real.** No hay "casi todas". No hay "esta no
importa tanto". Si falla una, se vuelve al dry-run.

---

## Bloque A — Validación matemática (antes del dry-run)

- [ ] `lookahead-analysis` → `biased_entry: False` y `biased_exit: False` en todos los indicadores
- [ ] `recursive-analysis` → desvío < 0.1% con `startup_candle_count = 900`
- [ ] **≥ 100 operaciones** en el periodo in-sample (2023-02 → 2024-12)
- [ ] **≥ 50 operaciones** en el periodo out-of-sample (2025-01 → hoy)
- [ ] Valor esperado por operación **positivo después de comisiones** al 0.1%/lado
- [ ] Sigue siendo positivo al **0.15%/lado** (prueba de estrés de slippage)
- [ ] Profit factor **> 1.3** out-of-sample
- [ ] Sharpe **> 0.5** out-of-sample
- [ ] Max drawdown out-of-sample **< 20%**
- [ ] Comparación contra `BuyAndHoldBTC`: la estrategia gana en **profit** o en **profit/drawdown**
- [ ] Walk-forward: **al menos 4 de 6 ventanas** semestrales positivas
- [ ] El profit **no** depende de un solo mes (`--breakdown month`). Si quitas el mejor mes, sigue positivo
- [ ] El profit **no** depende de una sola operación. Si quitas la mejor, sigue positivo
- [ ] `backtesting-analysis` revisado: entiendo de qué `exit_tag` sale el dinero

> **Si el out-of-sample es mucho peor que el in-sample, eso es el resultado.**
> No es "mala suerte" ni "el mercado cambió". Es la medición de cuánto
> sobreajustaste. Volver al diseño, no reoptimizar sobre 2025.

---

## Bloque B — Dry-run (3 a 4 semanas mínimo)

- [ ] 21 días corridos **sin reiniciar el contenedor** ni editar la estrategia
- [ ] **≥ 15 operaciones cerradas** en el periodo (si hay menos, extender a 6 semanas)
- [ ] Resultado del dry-run **coherente con el backtest** del mismo periodo
      (correr `backtesting --timerange` sobre las mismas fechas y comparar)
- [ ] Diferencia de win rate dry-run vs backtest **< 15 puntos**
- [ ] Ninguna operación quedó "colgada" (orden sin llenar, par bloqueado, trade zombi)
- [ ] Las protecciones se dispararon al menos una vez y **se recuperaron solas**
- [ ] Resumen diario de Telegram llegó **todos los días** (prueba de que el cron y la API viven)
- [ ] Reinicio probado a propósito: `docker compose restart` y el bot recuperó su estado
- [ ] Revisado `user_data/logs/freqtrade.log` → sin `ERROR` ni `WARNING` recurrentes
- [ ] Sé interpretar `/status`, `/profit` y `/daily` sin tener que buscarlo

> **La divergencia dry-run vs backtest es el dato más valioso de todo el
> proceso.** El backtest es una hipótesis; el dry-run es la primera medición
> real del mismo periodo. Si no coinciden, el backtest miente — y el culpable
> suele ser el slippage, el relleno de órdenes limit, o un indicador recursivo.

---

## Bloque C — Infraestructura

- [ ] VM de Azure con **reinicio automático** del contenedor (`restart: unless-stopped` ✅ ya configurado)
- [ ] Monitoreo de disco: `df -h` con > 20% libre. Los logs y datos crecen
- [ ] Monitoreo de RAM: el bot no se acerca al límite de 1 GB (`docker stats`)
- [ ] NTP sincronizado (`timedatectl`). Un reloj desfasado rompe las firmas de Binance
- [ ] Backup del `.sqlite` programado (o aceptado explícitamente que se puede perder)
- [ ] Puerto 8080 **no** expuesto a internet (`sudo ss -tlnp | grep 8080` → solo 127.0.0.1)
- [ ] Firewall de Azure: solo SSH abierto, y preferiblemente con IP restringida
- [ ] Probado qué pasa si la VM se reinicia: el bot vuelve solo y no duplica operaciones

---

## Bloque D — Seguridad de la API key (al crearla)

- [ ] API key creada **solo para este bot**, no reutilizada
- [ ] Permiso **"Enable Spot Trading"** activado
- [ ] Permiso **"Enable Withdrawals"** DESACTIVADO ← no negociable
- [ ] Permiso de **futuros / margen** DESACTIVADO
- [ ] **Restricción por IP** activada con la IP pública de la VM de Azure
- [ ] IP de la VM es **estática** (si es dinámica, la restricción se rompe y el bot muere en silencio)
- [ ] Claves **solo** en `.env`, con `chmod 600`
- [ ] `git status` limpio: `.env` **no** aparece ni como untracked
- [ ] Verificado que `.gitignore` bloquea `.env` (`git check-ignore -v .env`)
- [ ] 2FA activo en la cuenta de Binance
- [ ] Anotado dónde revocar la key si algo sale mal, y probado que sé hacerlo

---

## Bloque E — El interruptor de apagado

Antes de poner un sol real, estas respuestas tienen que estar escritas, no pensadas:

- [ ] **Pérdida máxima aceptable en USDT** antes de apagar todo: `________`
- [ ] **Drawdown máximo aceptable en %** antes de apagar todo: `________`
- [ ] **Nº de días seguidos en pérdida** que me hacen apagar: `________`
- [ ] Sé ejecutar el apagado de emergencia sin dudar:

```bash
# 1. Dejar de abrir posiciones nuevas, mantener las abiertas
#    (Telegram)  /stopentry

# 2. Cerrar todo a mercado AHORA
#    (Telegram)  /forceexit all

# 3. Apagar el bot
docker compose down
```

- [ ] Acepto por escrito que **puedo perder los 40 USDT completos**
- [ ] Ese dinero no afecta nada más en mi vida si desaparece hoy

---

## Transición a real (cuando TODO lo anterior está marcado)

```bash
# 1. Crear la API key en Binance con las restricciones del Bloque D
# 2. Ponerla en .env (NUNCA en config.json)
nano .env
#    FREQTRADE__EXCHANGE__KEY=...
#    FREQTRADE__EXCHANGE__SECRET=...

# 3. Cambiar a real
#    En user_data/config.json:  "dry_run": false
#    Dejar dry_run_wallet como está: se ignora en real.

# 4. Arrancar con capital reducido las primeras 2 semanas
#    stake_amount: 5   y   max_open_trades: 2
#    Son ~10 USDT en riesgo, no 30. Primero verifica que la ejecución real
#    se parece al dry-run; después escalas.

docker compose down && docker compose up -d
docker compose logs -f
```

### Primeras 72 horas en real — verificación obligatoria

- [ ] La primera orden se llenó al precio esperado (comparar con el libro)
- [ ] **Slippage real medido** y comparado con el supuesto del backtest
- [ ] Comisión real cobrada = 0.1% (o menos si tienes BNB / descuentos)
- [ ] El stop se ejecutó correctamente al menos una vez
- [ ] Balance de Binance y balance del bot coinciden (`/balance`)

---

## Lo que esta checklist no puede darte

Un backtest validado y un dry-run limpio demuestran que **la implementación es
correcta y que hubo una ventaja en el pasado reciente**. No demuestran que la
ventaja persista. Los regímenes de mercado cambian y las estrategias de
retroceso en tendencia mueren cuando la tendencia muere.

Con 40 USDT, el objetivo honesto de esta fase no es ganar dinero: es **aprender a
operar sistemáticamente con riesgo real controlado**. El P/L de los primeros
meses es ruido estadístico. Lo que importa es que el sistema haga exactamente lo
que dijiste que haría.
