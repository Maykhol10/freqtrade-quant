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
Entrada (1h):              RSI(14) cruza AL ALZA 35  Y  close > EMA50(1h)
Salida (1h):               RSI(14) > 70  O  close < EMA50(1h)  O  ROI  O  stop
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

        conditions = (
            # 1. Estructura mayor alcista (4h, vela ya cerrada)
            (dataframe[f"uptrend_{self.inf_timeframe}"] == 1)
            # 2. Retroceso agotandose: el RSI CRUZA hacia arriba el umbral.
            #    Usamos cruce, no "rsi < 35", para no comprar en caida libre.
            & (qtpylib.crossed_above(dataframe["rsi"], self.buy_rsi.value))
            # 3. El precio aguanta sobre su EMA50 de 1h -> retroceso, no ruptura
            & (dataframe["close"] > dataframe["ema50"])
            # 4. Sanidad: vela con volumen real
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[conditions, ["enter_long", "enter_tag"]] = (1, "pullback_rsi")
        return dataframe

    # ------------------------------------------------------------------ #
    #  Salida por senal
    # ------------------------------------------------------------------ #
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # a) Sobrecompra: tomamos ganancia en fuerza
        overbought = qtpylib.crossed_above(dataframe["rsi"], self.sell_rsi.value)

        # b) Perdida de estructura: el cierre pierde la EMA50 de 1h.
        #    Es la salida que de verdad protege: no espera al stop.
        lost_trend = qtpylib.crossed_below(dataframe["close"], dataframe["ema50"])

        dataframe.loc[overbought, ["exit_long", "exit_tag"]] = (1, "rsi_overbought")
        dataframe.loc[lost_trend, ["exit_long", "exit_tag"]] = (1, "lost_ema50")
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
