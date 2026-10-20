#!/usr/bin/env python3
"""
Prueba de lookahead por truncamiento.

    python3 scripts/bias_check.py TrendRiderV1
    python3 scripts/bias_check.py TrendPullbackV1 --pairs BTC/USDT ETH/USDT

Por que existe
--------------
`freqtrade lookahead-analysis` falla cuando la estrategia necesita mucho
calentamiento: recorta el periodo para la prueba y el calentamiento se come la
ventana entera, asi que no captura operaciones y cancela el test ("too few
trades caught"). Con `startup_candle_count = 1500` eso pasa siempre.

Esta prueba hace la comprobacion directa, que es la definicion misma de
lookahead:

    Si calculo los indicadores con TODA la serie y luego los calculo otra vez
    con la serie CORTADA en el instante t, el valor en t tiene que ser
    identico. Si cambia, el calculo con la serie completa estaba usando datos
    posteriores a t -- es decir, el futuro.

Se prueban varios puntos de corte repartidos por el periodo y se compara tanto
el valor de cada indicador como la senal de entrada resultante.

Limitacion: comprueba `populate_indicators` y `populate_entry_trend`, no
`custom_stoploss` ni la simulacion de ordenes. No sustituye a
`lookahead-analysis` cuando este si consigue correr; lo complementa.
"""

import argparse
import sys

from freqtrade.configuration import Configuration
from freqtrade.data.dataprovider import DataProvider
from freqtrade.data.history import load_pair_history
from freqtrade.enums import RunMode
from freqtrade.resolvers import StrategyResolver

TOL = 1e-9


class CutDataProvider(DataProvider):
    """
    DataProvider que devuelve las series informative CORTADAS en un instante.

    Sin esto la prueba seria invalida: la estrategia pide la serie diaria al
    DataProvider, no al dataframe que le paso, asi que recibiria el historico
    completo -- incluido el futuro -- aunque yo cortara la serie de 4h.
    Cortar las dos es lo que convierte esto en una prueba de lookahead real.
    """

    def __init__(self, config, cache):
        super().__init__(config, None)
        self._cut_cache = cache     # {(pair, timeframe): dataframe completo}
        self.cut_ts = None          # None = sin corte

    def get_pair_dataframe(self, pair, timeframe=None, candle_type=""):
        df = self._cut_cache.get((pair, timeframe))
        if df is None:
            return super().get_pair_dataframe(pair, timeframe, candle_type)
        if self.cut_ts is None:
            return df.copy()
        return df[df["date"] <= self.cut_ts].copy()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("strategy")
    ap.add_argument("--config", action="append",
                    default=["user_data/config.json"])
    ap.add_argument("--pairs", nargs="+", default=None)
    ap.add_argument("--cuts", type=int, default=8,
                    help="Cuantos puntos de corte probar (defecto 8)")
    args = ap.parse_args()

    cfg = Configuration.from_files(args.config)
    cfg["strategy"] = args.strategy
    cfg["runmode"] = RunMode.BACKTEST
    strategy = StrategyResolver.load_strategy(cfg)

    tf = strategy.timeframe
    inf_tf = getattr(strategy, "inf_timeframe", None)
    pairs = args.pairs or cfg["exchange"]["pair_whitelist"]
    dd = cfg["datadir"]
    startup = strategy.startup_candle_count
    fmt = cfg.get("dataformat_ohlcv", "feather")

    # Cache de las series informative, para poder cortarlas
    cache = {}
    if inf_tf:
        for p in pairs:
            d = load_pair_history(p, inf_tf, dd, data_format=fmt)
            if not d.empty:
                cache[(p, inf_tf)] = d

    strategy.dp = CutDataProvider(cfg, cache)

    print(f"Prueba de lookahead por truncamiento")
    print(f"  estrategia:   {args.strategy}")
    print(f"  timeframe:    {tf}" + (f"  (informative {inf_tf})" if inf_tf else ""))
    print(f"  calentamiento: {startup} velas")
    print(f"  pares:        {', '.join(pairs)}")
    print()

    fallos = 0
    probados = 0

    for pair in pairs:
        full = load_pair_history(pair, tf, dd, data_format=fmt)
        if full.empty or len(full) < startup + 200:
            print(f"  {pair:10} sin datos suficientes, se omite")
            continue

        # Indicadores y senales con la serie COMPLETA (incluido el futuro)
        strategy.dp.cut_ts = None
        ref = strategy.advise_indicators(full.copy(), {"pair": pair})
        ref = strategy.advise_entry(ref, {"pair": pair})

        # Columnas numericas a comparar (las que crea la estrategia)
        cols = [c for c in ref.columns
                if c not in ("date", "open", "high", "low", "close", "volume")
                and ref[c].dtype.kind in "fiub"]

        # Puntos de corte repartidos por la parte util de la serie
        lo, hi = startup + 50, len(full) - 2
        if hi <= lo:
            continue
        cortes = [lo + round(i * (hi - lo) / (args.cuts - 1))
                  for i in range(args.cuts)]

        malas = {}
        for corte in cortes:
            # La serie tal como existia en el instante del corte.
            # Se corta la base Y la informative: si solo se cortara la base,
            # la estrategia recibiria el diario completo y la prueba no
            # probaria nada.
            ts = full["date"].iat[corte]
            strategy.dp.cut_ts = ts
            cut = full.iloc[:corte + 1].copy()
            got = strategy.advise_indicators(cut, {"pair": pair})
            got = strategy.advise_entry(got, {"pair": pair})

            if got["date"].iat[-1] != ts:
                continue
            probados += 1

            for c in cols:
                if c not in got.columns:
                    continue
                a = ref[c].iat[corte]
                b = got[c].iat[-1]
                # NaN en los dos lados cuenta como igual
                if a != a and b != b:
                    continue
                if a != a or b != b:
                    malas.setdefault(c, 0)
                    malas[c] += 1
                    continue
                denom = max(abs(float(a)), 1.0)
                if abs(float(a) - float(b)) / denom > TOL:
                    malas.setdefault(c, 0)
                    malas[c] += 1

        if malas:
            fallos += 1
            print(f"  {pair:10} SESGO DETECTADO en {len(malas)} indicador(es):")
            for c, n in sorted(malas.items(), key=lambda kv: -kv[1]):
                print(f"               {c:24} difiere en {n}/{len(cortes)} cortes")
        else:
            print(f"  {pair:10} OK   {len(cols)} indicadores x {len(cortes)} cortes, "
                  f"sin diferencias")

    print()
    if fallos:
        print(f"  RESULTADO: SESGO en {fallos} par(es).")
        print("  La estrategia usa informacion posterior a la vela que evalua.")
        print("  NO seguir adelante hasta corregirlo.")
        sys.exit(1)

    print(f"  RESULTADO: sin sesgo detectado ({probados} comparaciones).")
    print("  Los indicadores y las senales en el instante t son identicos")
    print("  calculados con la serie completa o cortada en t.")
    print()
    print("  Ojo: esto cubre populate_indicators y populate_entry_trend.")
    print("  No cubre custom_stoploss ni la simulacion de ordenes.")
    sys.exit(0)


if __name__ == "__main__":
    main()
