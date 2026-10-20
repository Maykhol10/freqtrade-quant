# pragma pylint: disable=missing-docstring, invalid-name, too-many-locals
"""
TrendPullbackV1
===============
Estrategia deliberadamente simple: comprar retrocesos DENTRO de una tendencia
alcista confirmada en un timeframe superior. Spot, solo largos, sin apalancamiento.

Tesis
-----
El sesgo historico de BTC/ETH es alcista. Si solo compramos cuando la estructura
mayor (4h) es alcista y entramos en sobreventa de corto plazo (1h), capturamos la
continuacion y evitamos el "buy the dip" en mercado bajista, que es donde mueren
las estrategias de reversion a la media.

Logica
------
Filtro de tendencia (4h):  EMA50 > EMA200  Y  close > EMA200
Entrada (1h):              SETUP   RSI(14) toco < 35 en las ultimas 12 velas
                           GATILLO el cierre CRUZA al alza la EMA50 de 1h
Salida (1h):               RSI(14) > 70  O  ROI  O  stop por ATR  O  trailing

La entrada es de dos etapas a proposito. La version inicial pedia el cruce de
RSI y el precio sobre la EMA50 en la MISMA vela, y eso resulto casi imposible:
5 senales en 45 meses. Ver populate_entry_trend() para la medicion.
Stop:                      ATR(14) x 2 desde la entrada, acotado entre -1.5% y -5%
Trailing:                  se activa en +3%, bloquea ~+1%

Anti-lookahead
--------------
1. process_only_new_candles = True  -> solo velas cerradas.
2. merge_informative_pair() desplaza la serie 4h: la vela de las 12:00 no esta
   disponible hasta las 16:00. Nunca se lee el futuro.
3. custom_stoploss ancla el ATR a la vela DE ENTRADA via timeframe_to_prev_date,
   no a la vela actual: el stop no se recalcula con informacion posterior.
4. Validar siempre con:
     freqtrade lookahead-analysis --strategy TrendPullbackV1
     freqtrade recursive-analysis --strategy TrendPullbackV1

Proyecto: freqtrade-quant  |  Version: 1 (boceto)
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame

from technical import qtpylib   # freqtrade.vendor.qtpylib esta deprecado

from freqtrade.exchange import timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IStrategy,
    IntParameter,
    merge_informative_pair,
    stoploss_from_absolute,
)


class TrendPullbackV1(IStrategy):

    # ------------------------------------------------------------------ #
    #  Configuracion base
    # ------------------------------------------------------------------ #
    INTERFACE_VERSION = 3

    timeframe = "1h"
    inf_timeframe = "4h"              # filtro de tendencia

    can_short = False                 # SPOT: solo largos
    process_only_new_candles = True   # CRITICO: nada de velas en formacion
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # EMA200 en 4h = 200 velas de 4h = 800 velas de 1h.
    # Las EMA son recursivas, damos margen extra para que converjan.
    # `recursive-analysis` dira si hace falta subirlo.
    startup_candle_count: int = 900

    # ------------------------------------------------------------------ #
    #  Gestion de riesgo
    # ------------------------------------------------------------------ #

    # Stop "duro" de respaldo. El stop real lo calcula custom_stoploss().
    stoploss = -0.05

    use_custom_stoploss = True

    # OJO: con use_custom_stoploss=True Freqtrade ignora trailing_stop.
    # El trailing se implementa explicitamente DENTRO de custom_stoploss()
    # para que no haya ambiguedad sobre que logica manda.
    trailing_stop = False

    # Escalera de toma de ganancias (minutos -> profit objetivo).
    # Es un parche sobre la salida por senal: si el RSI nunca llega a 70,
    # el ROI cierra la operacion. Ajustar con cuidado: una escalera agresiva
    # infla el win rate y puede esconder que no hay ventaja real.
    minimal_roi = {
        "0": 0.08,       # +8% inmediato
        "240": 0.04,     # tras 4h basta +4%
        "720": 0.02,     # tras 12h basta +2%
        "1440": 0.005,   # tras 24h salir con casi nada antes que arriesgar
    }

    # ------------------------------------------------------------------ #
    #  Protecciones (DEBEN vivir aqui: en config.json estan deprecadas)
    # ------------------------------------------------------------------ #
    @property
    def protections(self):
        return [
            {
                # Tras cerrar, no reentrar en el mismo par durante 3 velas.
                # Evita el "revenge trading" automatico.
                "method": "CooldownPeriod",
                "stop_duration_candles": 3,
            },
            {
                # 2 stops en 24 velas -> pausa 12 velas.
                # Sintoma de que el regimen cambio y el filtro va con retraso.
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 2,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                # Interruptor general: -25% de drawdown en 7 dias -> apagar 48 velas.
                "method": "MaxDrawdown",
                "lookback_period_candles": 168,
                "trade_limit": 5,
                "stop_duration_candles": 48,
                "max_allowed_drawdown": 0.25,
            },
        ]

    # ------------------------------------------------------------------ #
    #  Parametros optimizables -> SOLO 3. Mas que esto es sobreajuste.
    # ------------------------------------------------------------------ #
    # Con ~150-400 operaciones, optimizar 3 parametros ya es agresivo.
    # Regla: optimizar en 2023-2024 y NO tocar nada mirando 2025-2026.
    buy_rsi = IntParameter(28, 42, default=35, space="buy", optimize=True)
    sell_rsi = IntParameter(62, 80, default=70, space="sell", optimize=True)
    atr_mult = DecimalParameter(1.5, 3.0, default=2.0, decimals=1,
                                space="sell", optimize=True)

    # Ventana del setup: cuantas velas atras se busca la sobreventa.
    # 12 velas de 1h = medio dia. NO se optimiza a proposito: anadirlo al
    # hyperopt seria un cuarto parametro, y con ~240 operaciones tres ya es
    # agresivo. 12 es una eleccion de diseno, no un numero ajustado al pasado.
    PULLBACK_LOOKBACK = 12

    # Limites del stop. NO se optimizan: son restricciones de riesgo,
    # no parametros a ajustar contra el historico.
    STOP_CAP = 0.05        # nunca arriesgar mas de 5% en una operacion
    STOP_FLOOR = 0.015     # nunca pegar el stop a menos de 1.5% (seria ruido)

    # Trailing explicito
    TRAIL_TRIGGER = 0.03   # se activa en +3%
    TRAIL_DISTANCE = 0.02  # luego sigue 2% bajo el precio -> bloquea ~+1%

    # ------------------------------------------------------------------ #
    #  Informative pairs: la serie 4h de cada par del whitelist
    # ------------------------------------------------------------------ #
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.inf_timeframe) for pair in pairs]

    # ------------------------------------------------------------------ #
    #  Indicadores
    # ------------------------------------------------------------------ #
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # ---------- Timeframe superior: 4h ----------
        inf = self.dp.get_pair_dataframe(pair=metadata["pair"],
                                         timeframe=self.inf_timeframe)
        inf["ema50"] = ta.EMA(inf, timeperiod=50)
        inf["ema200"] = ta.EMA(inf, timeperiod=200)

        # Tendencia alcista confirmada: cruce de medias Y precio sobre la lenta.
        # La segunda condicion evita operar durante un cruce que ya se esta
        # deshaciendo (EMA50 > EMA200 tarda en invertirse en una caida rapida).
        inf["uptrend"] = (
            (inf["ema50"] > inf["ema200"]) & (inf["close"] > inf["ema200"])
        ).astype(int)

        # merge_informative_pair desplaza la serie 4h: la vela 4h solo se
        # considera disponible cuando CIERRA. Aqui esta el anti-lookahead.
        dataframe = merge_informative_pair(
            dataframe, inf, self.timeframe, self.inf_timeframe, ffill=True
        )

        # ---------- Timeframe base: 1h ----------
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # ATR relativo: sirve para diagnosticar en que regimen de volatilidad
        # la estrategia opera bien o mal. No decide nada (todavia).
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        return dataframe

    # ------------------------------------------------------------------ #
    #  Entrada
    # ------------------------------------------------------------------ #
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Entrada en dos etapas: SETUP y GATILLO.

        La version 1 pedia las dos cosas en la misma vela -- que el RSI cruzara
        al alza 35 Y que el cierre estuviera sobre la EMA50 de 1h -- y eso es
        casi imposible: medido sobre 2023-2026, en el 99% de los 815 cruces de
        RSI por 35 el cierre quedaba BAJO la EMA50 (mediana -1.34% en BTC,
        -1.74% en ETH). Que el RSI(14) caiga a 35 IMPLICA un retroceso lo bastante
        grande para perder la media de 50 periodos. Resultado: 5 senales en 45
        meses y 3 operaciones en el backtest.

        La correccion separa las dos condiciones en el tiempo:
          SETUP   el RSI toco sobreventa en alguna de las ultimas 12 velas
          GATILLO el cierre RECUPERA la EMA50 de 1h

        Asi se entra en la vuelta, no en la caida, que era la intencion original.
        Medido: 237 senales en el mismo periodo (~5.2/mes).
        """
        conditions = (
            # 1. Estructura mayor alcista (4h, vela ya cerrada)
            (dataframe[f"uptrend_{self.inf_timeframe}"] == 1)

            # 2. SETUP: hubo retroceso reciente. El .shift(1) es importante:
            #    la ventana mira las velas t-12 .. t-1, nunca la actual, asi que
            #    no se usa informacion de la vela que todavia se esta evaluando.
            & (dataframe["rsi"].shift(1)
               .rolling(self.PULLBACK_LOOKBACK).min() < self.buy_rsi.value)

            # 3. GATILLO: el precio confirma la vuelta recuperando su EMA50.
            #    Es un cruce, no un nivel: entramos en el momento de la
            #    recuperacion, no en cualquier vela que ya este por encima.
            & (qtpylib.crossed_above(dataframe["close"], dataframe["ema50"]))

            # 4. Sanidad: vela con volumen real
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[conditions, ["enter_long", "enter_tag"]] = (1, "pullback_rsi")
        return dataframe

    # ------------------------------------------------------------------ #
    #  Salida por senal
    # ------------------------------------------------------------------ #
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Unica salida por senal: sobrecompra. La proteccion la dan el stop por
        ATR, el trailing y el ROI.

        La version anterior tambien salia cuando el cierre perdia la EMA50 de
        1h. Con la entrada en dos etapas eso es contradictorio: se entra CUANDO
        el cierre cruza al alza la EMA50, asi que salir al perderla es entrar y
        salir en el mismo cruce. Medido en 2023-02 -> 2025-01: provocaba 91 de
        las 111 salidas con un 1.1% de acierto, y el stop por ATR nunca llegaba
        a dispararse porque esta salida se le adelantaba siempre.

        Se quita la regla en vez de ponerle un colchon. Un colchon del 1% daba
        -3.66% frente al -4.84% de quitarla, pero las dos pierden y elegir la
        menos mala por una decima en el in-sample es justo la clase de ajuste
        que este proyecto intenta evitar. Se prefiere la razon -- la regla
        contradice la entrada -- antes que el decimal.
        """
        overbought = qtpylib.crossed_above(dataframe["rsi"], self.sell_rsi.value)
        dataframe.loc[overbought, ["exit_long", "exit_tag"]] = (1, "rsi_overbought")
        return dataframe

    # ------------------------------------------------------------------ #
    #  Stop dinamico por ATR + trailing explicito
    # ------------------------------------------------------------------ #
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> Optional[float]:
        """
        Devuelve el stop RELATIVO a current_rate (valor negativo).

        Dos regimenes:
          - Antes de +3%: stop fijo a 2xATR de la vela de entrada.
          - Desde +3%:    trailing al 2% bajo el precio actual.

        Freqtrade solo acepta stops que APRIETEN, nunca que se aflojen, asi que
        el stop nunca retrocede aunque el ATR se expanda.
        """

        # ---------- Fase 2: trailing ----------
        if current_profit >= self.TRAIL_TRIGGER:
            return -self.TRAIL_DISTANCE

        # ---------- Fase 1: stop por ATR anclado a la entrada ----------
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None   # mantiene el stoploss de clase (-5%)

        # Vela exacta en la que se abrio la operacion. Sin esto el stop
        # "respiraria" con el ATR actual = informacion que no existia al entrar.
        entry_date = timeframe_to_prev_date(self.timeframe, trade.open_date_utc)
        entry_candle = dataframe.loc[dataframe["date"] == entry_date]

        if entry_candle.empty:
            return None

        atr = entry_candle["atr"].iat[0]
        if atr is None or atr <= 0:
            return None

        # Precio de stop absoluto
        stop_price = trade.open_rate - (self.atr_mult.value * atr)

        # Acotar: ni mas lejos del 5% ni mas cerca del 1.5%
        hard_cap = trade.open_rate * (1 - self.STOP_CAP)
        hard_floor = trade.open_rate * (1 - self.STOP_FLOOR)
        stop_price = max(stop_price, hard_cap)     # no arriesgar mas de 5%
        stop_price = min(stop_price, hard_floor)   # no pegarlo al precio

        return stoploss_from_absolute(
            stop_price, current_rate, is_short=False, leverage=1.0
        )

    # ------------------------------------------------------------------ #
    #  Grafico (freqtrade plot-dataframe)
    # ------------------------------------------------------------------ #
    plot_config = {
        "main_plot": {
            "ema50": {"color": "orange"},
            "ema50_4h": {"color": "blue"},
            "ema200_4h": {"color": "red"},
        },
        "subplots": {
            "RSI": {"rsi": {"color": "purple"}},
            "ATR %": {"atr_pct": {"color": "grey"}},
            "Tendencia 4h": {"uptrend_4h": {"color": "green"}},
        },
    }
