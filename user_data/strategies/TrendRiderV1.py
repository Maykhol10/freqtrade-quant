# pragma pylint: disable=missing-docstring, invalid-name, too-many-locals
"""
TrendRiderV1
============
Estrategia distinta a TrendPullbackV1, no una version ajustada de ella.

Por que existe
--------------
La medicion de TrendPullbackV1 (ver docs/RESULTADOS.md) dejo un numero que
define el problema real:

    ventaja bruta de la senal   +0.008% por operacion
    coste de transaccion        -0.200% por operacion

Con 0.2% de comision ida y vuelta, una estrategia que opera cada 14 horas
necesita una ventaja bruta superior al 0.2% por operacion. Para una senal
tecnica de corto plazo esa barra es altisima.

La conclusion no es "ajustar el umbral del RSI". Es cambiar el regimen:
MENOS operaciones y objetivos MAS GRANDES. Si una operacion busca un 10%, el
0.2% de coste es el 2% del objetivo en vez del 100%. La barra pasa de
imposible a dificil.

Tesis
-----
Seguimiento de tendencia, no reversion a la media. Se compra FUERZA, no
debilidad: una ruptura de maximos recientes dentro de una tendencia mayor
alcista. La mayoria de las operaciones pierden poco y unas pocas ganan mucho.
El win rate esperado es BAJO (35-45%) y eso no es un defecto: es la forma del
payoff. Lo que importa es que la ganancia media sea varias veces la perdida
media.

Logica
------
Filtro de tendencia (1d):  EMA50 > EMA200  Y  close > EMA200
Entrada (4h):              el cierre supera el maximo de las ultimas 30 velas
                           (5 dias), con ATR relativo por encima de un minimo
Salida:                    stop chandelier -- maximo alcanzado menos 3xATR
                           DIARIO (~12% en BTC). Con ATR de 4h el stop era del
                           4.6% y la duracion media caia a 1 dia.
                           Sin salida por senal. Sin escalera de ROI.

Las dos ausencias son deliberadas:

  - **Sin ROI escalonado.** Un seguidor de tendencia vive de las pocas
    operaciones que corren mucho. Cortarlas a +4% u +8% elimina justo la cola
    que paga todo lo demas. TrendPullbackV1 tenia una escalera agresiva y eso
    le inflaba el win rate mientras perdia dinero.
  - **Sin salida por sobrecompra.** En una tendencia el RSI se queda alto
    durante semanas. Salir por RSI>70 es salir al principio del movimiento.

Anti-lookahead
--------------
1. `process_only_new_candles = True`.
2. El maximo de Donchian usa `.shift(1)`: la ventana son las velas t-30..t-1,
   nunca la actual. Sin el shift, la vela que rompe el maximo formaria parte
   del maximo que tiene que romper -- lookahead clasico y silencioso.
3. `merge_informative_pair()` desplaza la serie diaria.
4. El stop usa `trade.max_rate`, que es el maximo alcanzado HASTA el momento
   de la evaluacion, no el maximo de toda la operacion.
5. El ATR diario llega por `merge_informative_pair`, que lo desplaza: la vela
   diaria no esta disponible hasta que cierra.

Proyecto: freqtrade-quant  |  Version: 1
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IntParameter,
    IStrategy,
    merge_informative_pair,
    stoploss_from_absolute,
)


class TrendRiderV1(IStrategy):

    INTERFACE_VERSION = 3

    timeframe = "4h"
    inf_timeframe = "1d"

    can_short = False
    process_only_new_candles = True

    # Sin salida por senal: la salida la decide el stop chandelier
    use_exit_signal = False
    exit_profit_only = False

    # EMA200 diaria = 200 dias = 1200 velas de 4h. Mas margen para que converja.
    startup_candle_count: int = 1500

    # ------------------------------------------------------------------ #
    #  Riesgo
    # ------------------------------------------------------------------ #

    # Stop de respaldo amplio. El real lo calcula custom_stoploss().
    # Un seguidor de tendencia necesita espacio: un stop corto te saca del
    # movimiento antes de que empiece.
    stoploss = -0.25

    use_custom_stoploss = True
    trailing_stop = False      # el trailing va dentro de custom_stoploss()

    # ROI practicamente desactivado: 10 = 1000%, inalcanzable.
    # Es a proposito -- ver la nota sobre la cola de ganancias arriba.
    minimal_roi = {"0": 10.0}

    # ------------------------------------------------------------------ #
    #  Protecciones
    # ------------------------------------------------------------------ #
    @property
    def protections(self):
        return [
            {
                # 2 velas de 4h = 8 horas. Corto a proposito: en una ruptura
                # valida no queremos quedarnos fuera del siguiente intento.
                "method": "CooldownPeriod",
                "stop_duration_candles": 2,
            },
            {
                # 4 stops en 30 velas (5 dias) -> pausa 12 velas (2 dias).
                # Con stops amplios, 4 seguidos significan que la tendencia
                # mayor va con retraso respecto al precio.
                "method": "StoplossGuard",
                "lookback_period_candles": 30,
                "trade_limit": 4,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 180,   # 30 dias
                "trade_limit": 5,
                "stop_duration_candles": 30,      # 5 dias
                "max_allowed_drawdown": 0.25,
            },
        ]

    # ------------------------------------------------------------------ #
    #  Parametros: 3, igual que antes. Mas es sobreajuste.
    # ------------------------------------------------------------------ #
    # Ventana de la ruptura. 30 velas de 4h = 5 dias.
    breakout_window = IntParameter(15, 50, default=30, space="buy", optimize=True)

    # Multiplo de ATR del stop chandelier. Es el parametro que de verdad
    # decide el caracter de la estrategia: mas alto = menos operaciones,
    # mas largas, con mayor recorrido.
    atr_mult = DecimalParameter(2.0, 4.5, default=3.0, decimals=1,
                               space="sell", optimize=True)

    # Volatilidad minima para operar. Una ruptura en un mercado plano suele ser
    # ruido, y el coste fijo del 0.2% pesa mas cuando el movimiento es pequeno.
    min_atr_pct = DecimalParameter(0.005, 0.025, default=0.010, decimals=3,
                                   space="buy", optimize=True)

    # No optimizables: restricciones de riesgo, no parametros.
    STOP_CAP = 0.25        # el stop nunca se aleja mas del 25% de la entrada
    STOP_FLOOR = 0.03      # ni se pega a menos del 3%

    # Riesgo por operacion como fraccion del capital.
    #
    # Es la correccion del problema que destapo la primera medicion: con stake
    # fijo de 8 USDT y stop variable, el riesgo por operacion variaba con la
    # volatilidad del par. Ocho operaciones tocaron el tope del 25% y se
    # comieron 15.3 USDT: el 38% de una cuenta de 40.
    #
    # La solucion ortodoxa no es estrechar el stop -- eso convertiria el
    # chandelier en un stop fijo y eliminaria la adaptacion a volatilidad, que
    # es justo lo que lo hace funcionar. Es invertir la relacion: el stop lo
    # dicta la volatilidad y el TAMANO se calcula para que la perdida maxima
    # sea siempre la misma fraccion del capital.
    #
    #     tamano = (capital x riesgo) / distancia_al_stop
    #
    # 2% es el limite superior de la practica estandar. Con 4 posiciones
    # abiertas, el peor caso simultaneo es un 8% del capital.
    RISK_PER_TRADE = 0.02

    # ------------------------------------------------------------------ #
    def informative_pairs(self):
        return [(pair, self.inf_timeframe) for pair in self.dp.current_whitelist()]

    # ------------------------------------------------------------------ #
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # ---------- Diario: filtro de tendencia ----------
        inf = self.dp.get_pair_dataframe(pair=metadata["pair"],
                                         timeframe=self.inf_timeframe)
        inf["ema50"] = ta.EMA(inf, timeperiod=50)
        inf["ema200"] = ta.EMA(inf, timeperiod=200)
        inf["uptrend"] = (
            (inf["ema50"] > inf["ema200"]) & (inf["close"] > inf["ema200"])
        ).astype(int)

        # ATR DIARIO para el stop. Es la correccion que hizo falta tras medir:
        # 3xATR de 4h da un stop del 4.6% en BTC y se toca en horas, asi que la
        # duracion media salia de 1 dia cuando el diseno esperaba semanas.
        # 3xATR diario da ~12%, que es la escala del movimiento que se intenta
        # capturar. El stop debe medirse en el horizonte de la operacion, no en
        # el de la vela que la dispara.
        inf["atr"] = ta.ATR(inf, timeperiod=14)

        dataframe = merge_informative_pair(
            dataframe, inf, self.timeframe, self.inf_timeframe, ffill=True
        )

        # ---------- 4h ----------
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # Maximo de Donchian de la ventana ANTERIOR.
        # El .shift(1) es el detalle que separa una ruptura real de un
        # lookahead: sin el, la vela actual entra en su propio maximo y la
        # condicion "close > max" se vuelve casi imposible o trivial segun
        # el caso, pero en ambos esta mirando informacion de su propia vela.
        dataframe["donchian_high"] = (
            dataframe["high"].shift(1)
            .rolling(self.breakout_window.value).max()
        )

        # Solo para diagnostico en backtesting-analysis
        dataframe["dist_ema200_1d"] = (
            dataframe["close"] / dataframe[f"ema200_{self.inf_timeframe}"] - 1
        )

        return dataframe

    # ------------------------------------------------------------------ #
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = (
            # 1. Tendencia mayor alcista (diaria, vela ya cerrada)
            (dataframe[f"uptrend_{self.inf_timeframe}"] == 1)

            # 2. Ruptura: el cierre supera el maximo de las ultimas N velas.
            #    Se compra fuerza, no debilidad.
            & (dataframe["close"] > dataframe["donchian_high"])

            # 3. Hay volatilidad suficiente para que el movimiento pague el coste
            & (dataframe["atr_pct"] > self.min_atr_pct.value)

            # 4. Sanidad
            & (dataframe["volume"] > 0)
            & (dataframe["donchian_high"].notna())
        )

        dataframe.loc[conditions, ["enter_long", "enter_tag"]] = (1, "breakout")
        return dataframe

    # ------------------------------------------------------------------ #
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Sin salida por senal a proposito. El stop chandelier decide.
        dataframe["exit_long"] = 0
        return dataframe

    # ------------------------------------------------------------------ #
    def custom_stake_amount(self, pair: str, current_time: datetime,
                            current_rate: float, proposed_stake: float,
                            min_stake: Optional[float], max_stake: float,
                            leverage: float, entry_tag: Optional[str],
                            side: str, **kwargs) -> float:
        """
        Tamano de posicion por riesgo fijo, no por stake fijo.

            tamano = (capital x RISK_PER_TRADE) / distancia_al_stop

        La distancia al stop es la misma que usara custom_stoploss() en la
        primera evaluacion: 3xATR diario, acotada entre STOP_FLOOR y STOP_CAP.
        Asi la perdida si salta el stop es ~RISK_PER_TRADE del capital, sea el
        par BTC (ATR diario ~4%) o SOL (~7.5%).

        Consecuencia que conviene ver, no esconder: en los pares mas volatiles
        el tamano calculado cae por debajo del minimo que acepta Binance (~5
        USDT de nocional). Freqtrade descarta esas entradas automaticamente, y
        eso es lo correcto -- significa que **con 40 USDT no se puede tomar esa
        operacion con riesgo aceptable**. La alternativa seria tomarla con
        riesgo excesivo, que es lo que hacia la version anterior.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return proposed_stake

        atr = dataframe[f"atr_{self.inf_timeframe}"].iat[-1]
        if atr is None or atr <= 0 or current_rate <= 0:
            return proposed_stake

        # Distancia relativa al stop, con los mismos limites que custom_stoploss
        stop_dist = (self.atr_mult.value * atr) / current_rate
        stop_dist = max(min(stop_dist, self.STOP_CAP), self.STOP_FLOOR)

        # Capital de referencia. En backtest y en dry-run wallets refleja el
        # equity actual, asi que el riesgo escala con la cuenta.
        capital = None
        if self.wallets is not None:
            try:
                capital = self.wallets.get_total_stake_amount()
            except Exception:
                capital = None
        if not capital or capital <= 0:
            capital = float(self.config.get("available_capital")
                            or self.config.get("dry_run_wallet") or 0) or proposed_stake

        stake = (capital * self.RISK_PER_TRADE) / stop_dist

        # No pasarse del maximo disponible. El minimo NO se fuerza: si queda
        # por debajo, Freqtrade descarta la entrada, que es el comportamiento
        # deseado (ver docstring).
        return min(stake, max_stake)

    # ------------------------------------------------------------------ #
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> Optional[float]:
        """
        Stop chandelier: se cuelga del maximo alcanzado, no del precio de
        entrada ni del precio actual.

            stop = max_alcanzado - (atr_mult x ATR actual)

        Al principio esta por debajo de la entrada (es el stop de perdida);
        cuando el precio avanza, sube con el maximo y se convierte en el
        mecanismo que deja correr la ganancia. Freqtrade solo acepta stops que
        aprieten, asi que nunca retrocede.

        Se usa el ATR ACTUAL, no el de la entrada: en un seguidor de tendencia
        se quiere que el stop respire cuando la volatilidad se expande. Como
        Freqtrade ignora los aflojamientos, el efecto practico es que el stop
        sube mas despacio en mercados agitados, que es lo deseable.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None

        # ATR DIARIO, no el de 4h: el stop tiene que aguantar la escala temporal
        # del movimiento. Con ATR de 4h la duracion media salia de 1 dia.
        atr = dataframe[f"atr_{self.inf_timeframe}"].iat[-1]
        if atr is None or atr <= 0:
            return None

        # trade.max_rate es el maximo visto hasta AHORA en la operacion
        peak = max(trade.max_rate or trade.open_rate, trade.open_rate)
        stop_price = peak - (self.atr_mult.value * atr)

        # Acotar respecto a la ENTRADA, no al maximo: el tope de perdida
        # tiene que medirse contra lo que se arriesgo.
        hard_cap = trade.open_rate * (1 - self.STOP_CAP)
        stop_price = max(stop_price, hard_cap)

        # Y no pegarlo al precio actual
        ceiling = current_rate * (1 - self.STOP_FLOOR)
        stop_price = min(stop_price, ceiling)

        return stoploss_from_absolute(
            stop_price, current_rate, is_short=False, leverage=1.0
        )

    # ------------------------------------------------------------------ #
    plot_config = {
        "main_plot": {
            "donchian_high": {"color": "orange"},
            "ema200_1d": {"color": "red"},
            "ema50_1d": {"color": "blue"},
        },
        "subplots": {
            "ATR %": {"atr_pct": {"color": "grey"}},
            "Tendencia 1d": {"uptrend_1d": {"color": "green"}},
            "Dist. EMA200 1d": {"dist_ema200_1d": {"color": "purple"}},
        },
    }
