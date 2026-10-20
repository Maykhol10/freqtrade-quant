"""
BuyAndHoldBTC
=============
Benchmark obligatorio. No es una estrategia: es la vara de medir.

Compra en la primera vela disponible y NO vende nunca. Cualquier estrategia que
no supere esto (ajustada por drawdown) no justifica el riesgo operativo, los
costos de infraestructura, ni el tiempo invertido.

Uso (ver docs/COMANDOS.md):
    freqtrade backtesting --strategy BuyAndHoldBTC \
        --pairs BTC/USDT --max-open-trades 1 --stake-amount unlimited \
        --timerange 20230101-20250101

IMPORTANTE: usar --stake-amount unlimited y --max-open-trades 1 para que compre
con todo el capital. Con stake fijo de 10 USDT medirias el rendimiento de 10
USDT, no del portafolio, y la comparacion seria invalida.
"""

from pandas import DataFrame

from freqtrade.strategy import IStrategy


class BuyAndHoldBTC(IStrategy):

    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    # Nunca salir por ROI: 1000% es inalcanzable en el periodo de prueba
    minimal_roi = {"0": 10.0}

    # Nunca salir por stop
    stoploss = -0.99
    trailing_stop = False
    use_custom_stoploss = False

    # Nunca salir por senal
    use_exit_signal = False
    exit_profit_only = False

    process_only_new_candles = True
    startup_candle_count: int = 0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Senal permanente: entra en la primera vela y, como max_open_trades=1
        # y nunca vende, se queda dentro todo el periodo.
        dataframe.loc[dataframe["volume"] > 0, ["enter_long", "enter_tag"]] = (1, "hold")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe
