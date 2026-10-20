#!/usr/bin/env python3
"""
Genera un dashboard HTML autocontenido desde los resultados de backtest de Freqtrade.

    python3 scripts/report.py                              # usa el backtest mas reciente
    python3 scripts/report.py --in user_data/backtest_results/in_sample.json \
                             --benchmark user_data/backtest_results/buyhold.json \
                             --out docs/report.html --label "In-sample 2023-02 -> 2024-12"
    python3 scripts/report.py --oos                         # umbral de 50 operaciones

Solo libreria estandar: corre con el python3 del sistema, sin pip install.

Todas las metricas se calculan AQUI a partir de la lista de operaciones, no se
leen de los campos agregados del JSON. Dos razones:
  1. Los nombres de esos campos cambian entre versiones de Freqtrade.
  2. Un calculo propio es auditable: si el numero sorprende, se puede rastrear
     hasta las operaciones que lo producen.

Lo unico que se toma del JSON sin recalcular es el capital inicial.
"""

import argparse
import glob
import html
import json
import math
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- #
#  Paleta
#  Validada con scripts/validate_palette.py del metodo de dataviz:
#  categorica (azul, naranja) y polaridad (azul, rojo) pasan los 5
#  checks -- banda de luminosidad, piso de croma, separacion CVD,
#  piso de vision normal y contraste -- en light Y en dark.
# ---------------------------------------------------------------- #
UMBRAL = {
    "trades_in": 100,    # minimo para significancia estadistica in-sample
    "trades_oos": 50,    # minimo out-of-sample
    "profit_factor": 1.3,
    "drawdown": 0.20,
    "sharpe": 0.5,
    "sortino": 0.8,
}


# ================================================================ #
#  Carga
# ================================================================ #

def parse_dt(value):
    """Acepta los formatos de fecha que ha usado Freqtrade en distintas versiones."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


RESULTS_DIR = "user_data/backtest_results"


def read_raw(path):
    """
    Lee el JSON de un resultado de backtest.

    Freqtrade 2024.x+ empaqueta cada resultado en un .zip que contiene el JSON,
    el config usado, una copia de la estrategia y las series de wallet y
    market_change en feather. Las versiones anteriores escribian un .json
    suelto. Se soportan las dos.
    """
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            inner = [n for n in zf.namelist()
                     if n.endswith(".json")
                     and not n.endswith("_config.json")
                     and ".meta." not in n]
            if not inner:
                raise SystemExit(f"ERROR: {path} no contiene el JSON de resultados.")
            return json.loads(zf.read(sorted(inner)[0]))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def strategies_in(path):
    """Nombres de estrategia que contiene un resultado, sin cargarlo entero."""
    try:
        raw = read_raw(path)
    except Exception:
        return []
    return sorted((raw.get("strategy") or {}).keys())


def find_result(strategy=None):
    """
    El resultado mas reciente que contenga `strategy` (o el mas reciente si no
    se indica ninguna). Se busca por contenido y no por nombre de archivo porque
    Freqtrade ignora --export-filename y nombra los resultados por fecha.
    """
    candidates = []
    for pattern in ("*.zip", "*.json"):
        for path in glob.glob(os.path.join(RESULTS_DIR, pattern)):
            base = os.path.basename(path)
            if base.startswith(".") or base.endswith(".meta.json") \
               or base.endswith("_config.json") or "last_result" in base:
                continue
            candidates.append(path)

    candidates.sort(key=os.path.getmtime, reverse=True)
    for path in candidates:
        if strategy is None or strategy in strategies_in(path):
            return path
    return None


def load_result(path, strategy=None):
    """Devuelve (nombre_estrategia, dict_resultado) del archivo de backtest."""
    raw = read_raw(path)
    strategies = raw.get("strategy") or {}

    if not strategies:
        # Algunas versiones guardan el resultado plano
        if "trades" in raw:
            return (raw.get("strategy_name", "desconocida"), raw)
        raise SystemExit(
            f"ERROR: {path} no contiene resultados de estrategia.\n"
            "       ¿Exportaste con --export trades?"
        )

    if strategy:
        if strategy not in strategies:
            raise SystemExit(
                f"ERROR: {path} no contiene la estrategia '{strategy}'.\n"
                f"       Contiene: {', '.join(sorted(strategies))}"
            )
        return strategy, strategies[strategy]

    name = sorted(strategies)[0]
    return name, strategies[name]


# ================================================================ #
#  Calculo
# ================================================================ #

def nice_step(span, target_ticks=5):
    """Paso de eje redondeado a 1/2/5 x 10^n."""
    if span <= 0:
        return 1.0
    raw = span / max(target_ticks, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mult * mag:
            return mult * mag
    return 10 * mag


def compute(result, starting_balance_override=None):
    """Todas las metricas, calculadas desde la lista de operaciones."""
    trades = result.get("trades") or []
    if not trades:
        raise SystemExit("ERROR: el backtest no contiene ninguna operacion.")

    start_bal = starting_balance_override or result.get("starting_balance") or 0
    if not start_bal:
        start_bal = result.get("dry_run_wallet") or 40.0
    start_bal = float(start_bal)

    rows = []
    for t in trades:
        close = parse_dt(t.get("close_date"))
        if close is None:
            continue
        rows.append({
            "pair": t.get("pair", "?"),
            "open": parse_dt(t.get("open_date")),
            "close": close,
            "abs": float(t.get("profit_abs") or 0.0),
            "ratio": float(t.get("profit_ratio") or 0.0),
            "exit": t.get("exit_reason") or t.get("sell_reason") or "sin etiqueta",
            "enter": t.get("enter_tag") or "sin etiqueta",
            "mins": float(t.get("trade_duration") or 0.0),
        })
    rows.sort(key=lambda r: r["close"])

    n = len(rows)
    wins = [r for r in rows if r["abs"] > 0]
    losses = [r for r in rows if r["abs"] < 0]
    gross_win = sum(r["abs"] for r in wins)
    gross_loss = abs(sum(r["abs"] for r in losses))

    m = {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "flat": n - len(wins) - len(losses),
        "win_rate": len(wins) / n if n else 0.0,
        "avg_win": gross_win / len(wins) if wins else 0.0,
        "avg_loss": -gross_loss / len(losses) if losses else 0.0,
        "ev": sum(r["abs"] for r in rows) / n if n else 0.0,
        "profit_abs": sum(r["abs"] for r in rows),
        "start_bal": start_bal,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "avg_mins": sum(r["mins"] for r in rows) / n if n else 0.0,
        "first": rows[0]["close"],
        "last": rows[-1]["close"],
        # Apertura de la primera operacion: es la que marca el inicio real del
        # periodo cubierto. Para un buy & hold de una sola operacion, la fecha
        # de cierre no dice nada del inicio.
        "open_first": min((r["open"] for r in rows if r["open"]), default=rows[0]["close"]),
        "timeframe": result.get("timeframe", "?"),
        "max_open_trades": result.get("max_open_trades", "?"),
        "stake": result.get("stake_amount", "?"),
        "market_change": result.get("market_change"),
    }
    m["profit_pct"] = m["profit_abs"] / start_bal if start_bal else 0.0

    # ---------- Curva de capital y drawdown ----------
    equity = []
    cum = 0.0
    peak = start_bal
    max_dd = 0.0
    max_dd_abs = 0.0
    underwater = []
    for r in rows:
        cum += r["abs"]
        eq = start_bal + cum
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak else 0.0
        max_dd = max(max_dd, dd)
        max_dd_abs = max(max_dd_abs, peak - eq)
        equity.append({"t": r["close"], "eq": eq, "pct": cum / start_bal if start_bal else 0.0})
        underwater.append({"t": r["close"], "dd": -dd})
    m["equity"] = equity
    m["underwater"] = underwater
    m["max_dd"] = max_dd
    m["max_dd_abs"] = max_dd_abs

    # ---------- Retornos diarios -> Sharpe y Sortino ----------
    # La serie se construye sobre TODO el calendario, con retorno 0 en los dias
    # sin cierres. Es la parte que importa:
    #
    # Una version anterior solo incluia los dias CON cierre de operacion y
    # anualizaba con sqrt(365). Con 194 operaciones en 1927 dias, solo 126 dias
    # (7%) tenian cierre, asi que anualizaba una serie de 126 observaciones como
    # si fuera diaria: el Sharpe salia 3.88 en vez de 0.98, inflado ~4x. Un
    # Sharpe de 3.88 describe una estrategia de primer nivel mundial; 0.98 es
    # una estrategia decente. La diferencia entre esos dos numeros es la
    # diferencia entre poner dinero y no ponerlo.
    #
    # Los dias planos tambien son dias: diluyen la media y bajan el ratio, que
    # es exactamente lo que debe pasar en una estrategia de baja frecuencia.
    by_day = {}
    for r in rows:
        by_day.setdefault(r["close"].date(), 0.0)
        by_day[r["close"].date()] += r["abs"]

    daily = []
    running = start_bal
    day = rows[0]["close"].date()
    last_day = rows[-1]["close"].date()
    while day <= last_day:
        pnl = by_day.get(day, 0.0)
        daily.append(pnl / running if running else 0.0)
        running += pnl
        day += timedelta(days=1)

    def stdev(xs):
        if len(xs) < 2:
            return 0.0
        mu = sum(xs) / len(xs)
        return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))

    mu = sum(daily) / len(daily) if daily else 0.0
    sd = stdev(daily)
    downside = [x for x in daily if x < 0]
    sd_down = stdev(downside) if len(downside) > 1 else 0.0
    ann = math.sqrt(365)

    m["sharpe"] = (mu / sd * ann) if sd else 0.0
    m["sortino"] = (mu / sd_down * ann) if sd_down else 0.0
    m["calendar_days"] = len(daily)
    m["trading_days"] = len(by_day)

    span_days = max((m["last"] - m["first"]).days, 1)
    m["span_days"] = span_days
    final = start_bal + m["profit_abs"]
    # CAGR: solo tiene sentido con un periodo razonable. Con una sola operacion
    # (el benchmark) span_days es 1 y la extrapolacion a 365 desborda el float,
    # ademas de no significar nada.
    m["cagr"] = None
    if start_bal and final > 0 and span_days >= 30:
        try:
            m["cagr"] = (final / start_bal) ** (365.0 / span_days) - 1
        except OverflowError:
            m["cagr"] = None
    m["trades_per_day"] = n / span_days

    # ---------- Agrupaciones ----------
    def group(key):
        out = {}
        for r in rows:
            g = out.setdefault(r[key], {"n": 0, "abs": 0.0, "wins": 0})
            g["n"] += 1
            g["abs"] += r["abs"]
            if r["abs"] > 0:
                g["wins"] += 1
        for g in out.values():
            g["win_rate"] = g["wins"] / g["n"] if g["n"] else 0.0
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["abs"]))

    m["by_pair"] = group("pair")
    m["by_exit"] = group("exit")

    monthly = {}
    for r in rows:
        k = r["close"].strftime("%Y-%m")
        g = monthly.setdefault(k, {"n": 0, "abs": 0.0})
        g["n"] += 1
        g["abs"] += r["abs"]
    m["monthly"] = dict(sorted(monthly.items()))

    # ---------- Histograma de P/L por operacion ----------
    ratios = [r["ratio"] for r in rows]
    lo, hi = min(ratios), max(ratios)
    bound = max(abs(lo), abs(hi)) or 0.01
    nbins = 15
    width = (2 * bound) / nbins
    bins = []
    for i in range(nbins):
        a = -bound + i * width
        bins.append({"a": a, "b": a + width, "c": a + width / 2, "n": 0})
    for x in ratios:
        idx = min(int((x + bound) / width), nbins - 1)
        bins[max(idx, 0)]["n"] += 1
    m["hist"] = bins
    m["best"] = max(rows, key=lambda r: r["abs"])
    m["worst"] = min(rows, key=lambda r: r["abs"])

    # ---------- Concentracion: ¿aguanta sin el mejor mes / la mejor operacion? ----------
    if m["monthly"]:
        best_month = max(m["monthly"].items(), key=lambda kv: kv[1]["abs"])
        m["best_month"] = best_month[0]
        m["sin_mejor_mes"] = m["profit_abs"] - best_month[1]["abs"]
    else:
        m["best_month"], m["sin_mejor_mes"] = "-", m["profit_abs"]
    m["sin_mejor_op"] = m["profit_abs"] - m["best"]["abs"]

    m["rows"] = rows
    return m


def evaluate(m, bench, oos):
    """Semaforo contra los umbrales de docs/VALIDACION.md."""
    min_trades = UMBRAL["trades_oos"] if oos else UMBRAL["trades_in"]
    checks = []

    def add(label, ok, valor, umbral, nota=""):
        checks.append({"label": label, "estado": ok, "valor": valor,
                       "umbral": umbral, "nota": nota})

    add("Numero de operaciones",
        "good" if m["n"] >= min_trades else ("warning" if m["n"] >= min_trades * 0.5 else "critical"),
        f"{m['n']}", f">= {min_trades}",
        "" if m["n"] >= min_trades else "muestra insuficiente: cualquier conclusion es fe, no estadistica")

    add("Valor esperado por operacion",
        "good" if m["ev"] > 0 else "critical",
        f"{m['ev']:+.4f} USDT", "> 0",
        "" if m["ev"] > 0 else "sin ventaja: cada operacion pierde dinero en promedio")

    pf = m["profit_factor"]
    add("Profit factor",
        "good" if pf > UMBRAL["profit_factor"] else ("warning" if pf > 1.0 else "critical"),
        ("inf" if pf == float("inf") else f"{pf:.2f}"), f"> {UMBRAL['profit_factor']}",
        "" if pf > UMBRAL["profit_factor"] else "entre 1.0 y 1.3 la ventaja no sobrevive al slippage")

    add("Max drawdown",
        "good" if m["max_dd"] < UMBRAL["drawdown"] else ("warning" if m["max_dd"] < 0.30 else "critical"),
        f"{m['max_dd']*100:.1f}%", f"< {UMBRAL['drawdown']*100:.0f}%")

    add("Sharpe",
        "good" if m["sharpe"] > UMBRAL["sharpe"] else ("warning" if m["sharpe"] > 0 else "critical"),
        f"{m['sharpe']:.2f}", f"> {UMBRAL['sharpe']}")

    add("Sortino",
        "good" if m["sortino"] > UMBRAL["sortino"] else ("warning" if m["sortino"] > 0 else "critical"),
        f"{m['sortino']:.2f}", f"> {UMBRAL['sortino']}")

    # Concentracion
    add("Aguanta sin el mejor mes",
        "good" if m["sin_mejor_mes"] > 0 else "critical",
        f"{m['sin_mejor_mes']:+.2f} USDT", "> 0",
        f"el mejor mes fue {m['best_month']}")

    add("Aguanta sin la mejor operacion",
        "good" if m["sin_mejor_op"] > 0 else "critical",
        f"{m['sin_mejor_op']:+.2f} USDT", "> 0")

    # Benchmark
    if bench:
        mejor_profit = m["profit_pct"] > bench["profit_pct"]
        if bench["dd_medible"]:
            r_est = m["profit_pct"] / m["max_dd"] if m["max_dd"] else float("inf")
            r_bh = bench["profit_pct"] / bench["max_dd"] if bench["max_dd"] else float("inf")
            mejor_ratio = r_est > r_bh
            nota = ("gana en profit" if mejor_profit else
                    ("gana en profit/drawdown" if mejor_ratio else
                     "pierde en ambos: la estrategia no justifica el riesgo operativo"))
            estado = "good" if (mejor_profit or mejor_ratio) else "critical"
        else:
            # Buy & hold cierra una sola operacion, asi que su curva de capital
            # tiene un unico punto y el drawdown sale 0 por construccion, no
            # porque no lo haya tenido. Comparar ratios aqui seria inventar un dato.
            mejor_ratio = False
            estado = "good" if mejor_profit else "warning"
            nota = ("gana en profit" if mejor_profit else
                    "pierde en profit; el drawdown del benchmark no es medible "
                    "desde una sola operacion, asi que la comparacion por "
                    "profit/drawdown queda pendiente")
        add("Supera a comprar y mantener", estado,
            f"{m['profit_pct']*100:+.1f}% vs {bench['profit_pct']*100:+.1f}%",
            "profit o ratio profit/DD", nota)
    else:
        add("Supera a comprar y mantener", "warning", "sin medir",
            "profit o ratio profit/DD",
            "corre make benchmark-in y pasa el resultado con --benchmark")

    return checks


# ================================================================ #
#  SVG
# ================================================================ #

PLOT = {"w": 760, "h": 240, "l": 54, "r": 16, "t": 12, "b": 30}


def esc(s):
    return html.escape(str(s), quote=True)


def fmt_pct(x, dec=1):
    return f"{x*100:+.{dec}f}%"


def _axis_y(vals, pad=0.08):
    lo, hi = min(vals), max(vals)
    if lo == hi:
        lo, hi = lo - 0.01, hi + 0.01
    span = hi - lo
    lo -= span * pad
    hi += span * pad
    step = nice_step(hi - lo)
    lo = math.floor(lo / step) * step
    hi = math.ceil(hi / step) * step
    ticks = []
    v = lo
    while v <= hi + step * 0.001:
        ticks.append(v)
        v += step
    return lo, hi, ticks


def svg_timeseries(series, reference=None, ref_label="", y_fmt=fmt_pct,
                   chart_id="c", fill=True):
    """
    Serie temporal: linea de 2px + relleno al 10%. Rejilla hairline solida.
    `reference` dibuja una linea horizontal de referencia con etiqueta directa
    (no es una segunda serie: el buy & hold solo se conoce en su valor final).
    """
    P = PLOT
    pw = P["w"] - P["l"] - P["r"]
    ph = P["h"] - P["t"] - P["b"]

    xs = [s["t"].timestamp() for s in series]
    ys = [s["v"] for s in series]
    vals = ys + ([reference] if reference is not None else []) + [0.0]
    ylo, yhi, yticks = _axis_y(vals)
    xlo, xhi = min(xs), max(xs)
    xspan = (xhi - xlo) or 1

    def X(t):
        return P["l"] + (t - xlo) / xspan * pw

    def Y(v):
        return P["t"] + (yhi - v) / (yhi - ylo) * ph

    out = [f'<svg class="chart" viewBox="0 0 {P["w"]} {P["h"]}" '
           f'role="img" aria-label="Serie temporal" data-chart="{chart_id}">']

    # Rejilla + eje Y
    for v in yticks:
        y = Y(v)
        out.append(f'<line class="grid" x1="{P["l"]}" y1="{y:.1f}" '
                   f'x2="{P["l"]+pw}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{P["l"]-8}" y="{y+3.5:.1f}" '
                   f'text-anchor="end">{esc(y_fmt(v, 0))}</text>')

    # Linea cero marcada como eje
    if ylo < 0 < yhi:
        out.append(f'<line class="axis" x1="{P["l"]}" y1="{Y(0):.1f}" '
                   f'x2="{P["l"]+pw}" y2="{Y(0):.1f}"/>')

    # Eje X: 5 marcas
    nticks = min(5, len(series))
    for i in range(nticks):
        idx = round(i * (len(series) - 1) / max(nticks - 1, 1))
        t = series[idx]["t"]
        out.append(f'<text class="tick" x="{X(t.timestamp()):.1f}" '
                   f'y="{P["t"]+ph+20}" text-anchor="middle">'
                   f'{t.strftime("%Y-%m")}</text>')

    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))

    if fill:
        base = Y(max(ylo, 0.0) if ylo < 0 else ylo)
        out.append(f'<polygon class="area s1" points="{X(xs[0]):.1f},{base:.1f} '
                   f'{pts} {X(xs[-1]):.1f},{base:.1f}"/>')

    out.append(f'<polyline class="line s1" points="{pts}"/>')

    # Referencia horizontal con etiqueta directa
    if reference is not None:
        ry = Y(reference)
        out.append(f'<line class="ref" x1="{P["l"]}" y1="{ry:.1f}" '
                   f'x2="{P["l"]+pw}" y2="{ry:.1f}"/>')
        out.append(f'<text class="reflabel" x="{P["l"]+pw-4}" y="{ry-6:.1f}" '
                   f'text-anchor="end">{esc(ref_label)}</text>')

    # Marcador final + etiqueta directa (solo el extremo, nunca cada punto)
    out.append(f'<circle class="dot s1" cx="{X(xs[-1]):.1f}" cy="{Y(ys[-1]):.1f}" r="4.5"/>')
    out.append(f'<text class="endlabel" x="{X(xs[-1])-8:.1f}" y="{Y(ys[-1])-10:.1f}" '
               f'text-anchor="end">{esc(y_fmt(ys[-1]))}</text>')

    # Capa de hover: crosshair invisible sobre todo el area de trazado
    out.append(f'<g class="hoverlayer"><line class="crosshair" x1="0" y1="{P["t"]}" '
               f'x2="0" y2="{P["t"]+ph}"/><circle class="hoverdot" r="5"/></g>')
    out.append(f'<rect class="hoverzone" x="{P["l"]}" y="{P["t"]}" '
               f'width="{pw}" height="{ph}" fill="transparent"/>')
    out.append("</svg>")
    return "\n".join(out)


def svg_columns(items, chart_id="c", y_fmt=lambda v, d=1: f"{v:+.1f}",
                x_rotate=False, polarity=True):
    """
    Columnas desde una linea base en 0. Polaridad por color (par divergente),
    tope redondeado 4px en el extremo de dato y recto en la base, hueco de 2px
    de superficie entre columnas vecinas.
    """
    P = dict(PLOT)
    P["b"] = 46 if x_rotate else 30
    P["h"] = P["t"] + 240 - 12 + P["b"]
    pw = P["w"] - P["l"] - P["r"]
    ph = P["h"] - P["t"] - P["b"]

    vals = [it["v"] for it in items] + [0.0]
    ylo, yhi, yticks = _axis_y(vals)

    def Y(v):
        return P["t"] + (yhi - v) / (yhi - ylo) * ph

    band = pw / max(len(items), 1)
    bw = min(24.0, max(band - 2.0, 2.0))       # <=24px, 2px de hueco
    zero = Y(0)

    out = [f'<svg class="chart" viewBox="0 0 {P["w"]} {P["h"]}" '
           f'role="img" aria-label="Columnas" data-chart="{chart_id}">']

    for v in yticks:
        y = Y(v)
        out.append(f'<line class="grid" x1="{P["l"]}" y1="{y:.1f}" '
                   f'x2="{P["l"]+pw}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{P["l"]-8}" y="{y+3.5:.1f}" '
                   f'text-anchor="end">{esc(y_fmt(v, 0))}</text>')
    out.append(f'<line class="axis" x1="{P["l"]}" y1="{zero:.1f}" '
               f'x2="{P["l"]+pw}" y2="{zero:.1f}"/>')

    step = max(1, len(items) // 14)
    for i, it in enumerate(items):
        cx = P["l"] + band * i + band / 2
        x = cx - bw / 2
        v = it["v"]
        cls = "pos" if (v >= 0 or not polarity) else "neg"
        h = abs(Y(v) - zero)
        r = min(4.0, h, bw / 2)
        if h < 0.6:
            continue
        if v >= 0:
            top = zero - h
            # Tope redondeado arriba (extremo de dato), recto en la base
            d = (f"M{x:.1f},{zero:.1f} V{top+r:.1f} Q{x:.1f},{top:.1f} {x+r:.1f},{top:.1f} "
                 f"H{x+bw-r:.1f} Q{x+bw:.1f},{top:.1f} {x+bw:.1f},{top+r:.1f} "
                 f"V{zero:.1f} Z")
        else:
            bot = zero + h
            d = (f"M{x:.1f},{zero:.1f} V{bot-r:.1f} Q{x:.1f},{bot:.1f} {x+r:.1f},{bot:.1f} "
                 f"H{x+bw-r:.1f} Q{x+bw:.1f},{bot:.1f} {x+bw:.1f},{bot-r:.1f} "
                 f"V{zero:.1f} Z")
        out.append(f'<path class="bar {cls}" d="{d}" data-i="{i}"/>')
        out.append(f'<rect class="barhit" x="{cx-band/2:.1f}" y="{P["t"]}" '
                   f'width="{band:.1f}" height="{ph:.1f}" data-i="{i}" fill="transparent"/>')

        if i % step == 0:
            label = esc(it["label"])
            if x_rotate:
                out.append(f'<text class="tick" transform="translate({cx:.1f},'
                           f'{P["t"]+ph+16}) rotate(-45)" text-anchor="end">{label}</text>')
            else:
                out.append(f'<text class="tick" x="{cx:.1f}" y="{P["t"]+ph+20}" '
                           f'text-anchor="middle">{label}</text>')
    out.append("</svg>")
    return "\n".join(out)


# ================================================================ #
#  HTML
# ================================================================ #

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --plane:#f9f9f7; --surface:#fcfcfb;
  --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
  --s1:#2a78d6; --s2:#eb6834;
  --pos:#2a78d6; --neg:#e34948;
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b;
  --good-ink:#006300;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --plane:#0d0d0d; --surface:#1a1a19;
    --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --s1:#3987e5; --s2:#d95926;
    --pos:#3987e5; --neg:#e66767;
    --good-ink:#0ca30c;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19;
  --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
  --s1:#3987e5; --s2:#d95926;
  --pos:#3987e5; --neg:#e66767;
  --good-ink:#0ca30c;
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;padding:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px;line-height:1.55;
}
.wrap{max-width:1040px;margin:0 auto;padding:32px 16px 72px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;
  justify-content:space-between;margin-bottom:8px}
h1{font-size:1.45rem;margin:0 0 2px;letter-spacing:-0.01em}
h2{font-size:1.05rem;margin:0 0 4px;letter-spacing:-0.005em}
.sub{color:var(--ink2);font-size:0.875rem;margin:0}
.muted{color:var(--muted)}
#theme{
  background:var(--surface);color:var(--ink2);border:1px solid var(--border);
  border-radius:8px;padding:7px 12px;font:inherit;font-size:0.8rem;cursor:pointer;
}
#theme:hover{color:var(--ink)}
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:20px;margin:16px 0;
}
.grid3{display:grid;gap:16px;grid-template-columns:1fr;margin:16px 0}
@media (min-width:720px){.grid3{grid-template-columns:2fr 1fr}}

/* ---- Hero: exactamente una por vista ---- */
.hero .label{color:var(--ink2);font-size:0.8rem;text-transform:none;margin:0}
.hero .value{font-size:clamp(2.6rem,7vw,3.4rem);font-weight:650;line-height:1.05;
  letter-spacing:-0.02em;margin:4px 0 2px}
.hero .unit{font-size:0.95rem;font-weight:400;color:var(--ink2);margin-left:6px}
.hero .why{color:var(--ink2);font-size:0.825rem;margin:8px 0 0;max-width:46ch}
.up{color:var(--good-ink)}.down{color:var(--critical)}

/* ---- Stat tiles ---- */
.tiles{display:grid;gap:1px;background:var(--border);border:1px solid var(--border);
  border-radius:12px;overflow:hidden;grid-template-columns:repeat(2,1fr)}
@media (min-width:620px){.tiles{grid-template-columns:repeat(4,1fr)}}
.tile{background:var(--surface);padding:14px 16px}
.tile .k{color:var(--ink2);font-size:0.75rem;display:block;margin-bottom:2px}
.tile .v{font-size:1.3rem;font-weight:600;letter-spacing:-0.01em}
.tile .n{color:var(--muted);font-size:0.72rem;display:block;margin-top:1px}

/* ---- Charts ---- */
.chart{width:100%;height:auto;display:block;overflow:visible;margin-top:10px}
.grid{stroke:var(--grid);stroke-width:1}
.axis{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:10.5px;font-variant-numeric:tabular-nums;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.line.s1{stroke:var(--s1)}
.area.s1{fill:var(--s1);opacity:0.10;stroke:none}
.dot.s1{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.ref{stroke:var(--s2);stroke-width:2;opacity:0.9}
.reflabel,.endlabel{fill:var(--ink2);font-size:11px;font-weight:600;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.bar.pos{fill:var(--pos)}
.bar.neg{fill:var(--neg)}
.barhit{cursor:crosshair}
.hoverlayer{opacity:0;pointer-events:none}
.hoverlayer.on{opacity:1}
.crosshair{stroke:var(--axis);stroke-width:1}
.hoverdot{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.hoverzone{cursor:crosshair}

/* ---- Legend ---- */
.legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:12px;
  font-size:0.8rem;color:var(--ink2)}
.legend span{display:inline-flex;align-items:center;gap:7px}
.key{width:14px;height:3px;border-radius:2px;flex:none}
.key.sq{width:11px;height:11px;border-radius:3px}

/* ---- Semaforo ---- */
table{width:100%;border-collapse:collapse;font-size:0.86rem}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--border)}
th{color:var(--ink2);font-weight:600;font-size:0.78rem}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:none}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:600;
  font-size:0.78rem;white-space:nowrap}
.badge .ico{font-size:0.9rem;line-height:1}
.badge.good{color:var(--good-ink)}
.badge.warning{color:#8a5d00}
.badge.critical{color:var(--critical)}
/* El ambar de "warning" no llega a 3:1 sobre la superficie clara, asi que en
   light se usa un paso mas oscuro. El icono + la palabra son la mitigacion:
   el color nunca carga el significado solo. */
:root[data-theme="dark"] .badge.warning{color:var(--warning)}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]) .badge.warning{color:var(--warning)}
}
details{margin-top:14px;border-top:1px solid var(--border);padding-top:10px}
summary{cursor:pointer;color:var(--ink2);font-size:0.8rem}
summary:hover{color:var(--ink)}
.banner{border-radius:10px;padding:14px 16px;margin:16px 0;font-size:0.9rem;
  border:1px solid var(--border);background:var(--surface)}
.banner strong{display:block;margin-bottom:3px}
.banner.good{border-left:3px solid var(--good)}
.banner.warning{border-left:3px solid var(--warning)}
.banner.critical{border-left:3px solid var(--critical)}
#tip{
  position:fixed;pointer-events:none;opacity:0;z-index:20;
  background:var(--surface);color:var(--ink);border:1px solid var(--border);
  border-radius:8px;padding:8px 10px;font-size:0.78rem;line-height:1.45;
  box-shadow:0 4px 14px rgba(0,0,0,0.13);max-width:240px;
  font-variant-numeric:tabular-nums;
}
#tip.on{opacity:1}
#tip b{font-weight:650}
footer{color:var(--muted);font-size:0.78rem;margin-top:40px;
  border-top:1px solid var(--border);padding-top:16px}
footer a{color:var(--ink2)}
@media print{
  body{background:#fff}
  .card{break-inside:avoid}
  #theme,#tip{display:none}
  details{display:block}
  details>summary{display:none}
}
"""

JS = """
(function(){
  var root=document.documentElement, btn=document.getElementById('theme');
  function cur(){ return root.getAttribute('data-theme') ||
    (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'); }
  function paint(){ btn.textContent = cur()==='dark' ? 'Tema claro' : 'Tema oscuro'; }
  btn.addEventListener('click',function(){
    root.setAttribute('data-theme', cur()==='dark'?'light':'dark'); paint();
  });
  paint();

  var tip=document.getElementById('tip');
  function show(html,x,y){
    tip.innerHTML=html; tip.classList.add('on');
    var r=tip.getBoundingClientRect();
    var left=Math.min(x+14, innerWidth-r.width-8);
    var top=Math.max(8, y-r.height-14);
    tip.style.left=left+'px'; tip.style.top=top+'px';
  }
  function hide(){ tip.classList.remove('on'); }

  var DATA=JSON.parse(document.getElementById('chartdata').textContent);

  // --- Series temporales: crosshair + punto mas cercano en X ---
  document.querySelectorAll('svg[data-chart]').forEach(function(svg){
    var id=svg.getAttribute('data-chart'), d=DATA[id];
    if(!d) return;

    if(d.kind==='series'){
      var zone=svg.querySelector('.hoverzone'),
          layer=svg.querySelector('.hoverlayer'),
          cross=svg.querySelector('.crosshair'),
          hdot=svg.querySelector('.hoverdot');
      if(!zone) return;
      function vb(e){
        var r=svg.getBoundingClientRect(), box=svg.viewBox.baseVal;
        return (e.clientX-r.left)/r.width*box.width;
      }
      function move(e){
        var x=vb(e), best=0, bd=1e9;
        for(var i=0;i<d.px.length;i++){
          var dist=Math.abs(d.px[i]-x);
          if(dist<bd){bd=dist;best=i;}
        }
        layer.classList.add('on');
        cross.setAttribute('x1',d.px[best]); cross.setAttribute('x2',d.px[best]);
        hdot.setAttribute('cx',d.px[best]); hdot.setAttribute('cy',d.py[best]);
        show('<b>'+d.label[best]+'</b><br>'+d.text[best], e.clientX, e.clientY);
      }
      zone.addEventListener('mousemove',move);
      zone.addEventListener('mouseleave',function(){layer.classList.remove('on');hide();});
    }

    if(d.kind==='cols'){
      svg.querySelectorAll('.barhit').forEach(function(hit){
        var i=+hit.getAttribute('data-i');
        hit.addEventListener('mousemove',function(e){
          show('<b>'+d.label[i]+'</b><br>'+d.text[i], e.clientX, e.clientY);
        });
        hit.addEventListener('mouseleave',hide);
      });
    }
  });
})();
"""


def tile(k, v, note="", cls=""):
    n = f'<span class="n">{esc(note)}</span>' if note else ""
    return (f'<div class="tile"><span class="k">{esc(k)}</span>'
            f'<span class="v {cls}">{esc(v)}</span>{n}</div>')


def table(headers, rows, numcols=()):
    th = "".join(f'<th class="{"num" if i in numcols else ""}">{esc(h)}</th>'
                 for i, h in enumerate(headers))
    body = []
    for r in rows:
        tds = "".join(f'<td class="{"num" if i in numcols else ""}">{c}</td>'
                      for i, c in enumerate(r))
        body.append(f"<tr>{tds}</tr>")
    return (f'<table><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


ICON = {"good": "&#10003;", "warning": "&#33;", "critical": "&#10007;"}
WORD = {"good": "PASA", "warning": "REVISAR", "critical": "FALLA"}


def badge(state):
    return (f'<span class="badge {state}"><span class="ico">{ICON[state]}</span>'
            f'{WORD[state]}</span>')


def render(m, bench, checks, meta):
    chartdata = {}

    # ---- Curva de rentabilidad ----
    serie = [{"t": e["t"], "v": e["pct"]} for e in m["equity"]]
    ref = bench["profit_pct"] if bench else None
    reflab = f'Buy & hold {fmt_pct(ref)}' if bench else ""
    svg_eq = svg_timeseries(serie, reference=ref, ref_label=reflab, chart_id="eq")
    P = PLOT
    pw = P["w"] - P["l"] - P["r"]
    ph = P["h"] - P["t"] - P["b"]
    xs = [s["t"].timestamp() for s in serie]
    ylo, yhi, _ = _axis_y([s["v"] for s in serie] + ([ref] if ref is not None else []) + [0.0])
    xlo, xspan = min(xs), (max(xs) - min(xs)) or 1
    chartdata["eq"] = {
        "kind": "series",
        "px": [round(P["l"] + (x - xlo) / xspan * pw, 1) for x in xs],
        "py": [round(P["t"] + (yhi - s["v"]) / (yhi - ylo) * ph, 1) for s in serie],
        "label": [s["t"].strftime("%Y-%m-%d %H:%M") for s in serie],
        "text": [f'Rentabilidad {fmt_pct(s["v"], 2)}<br>Capital '
                 f'{m["start_bal"] + s["v"] * m["start_bal"]:.2f} USDT<br>'
                 f'operacion {i+1} de {m["n"]}'
                 for i, s in enumerate(serie)],
    }

    # ---- Drawdown ----
    uw = [{"t": u["t"], "v": u["dd"]} for u in m["underwater"]]
    svg_dd = svg_timeseries(uw, chart_id="dd")
    ylo2, yhi2, _ = _axis_y([u["v"] for u in uw] + [0.0])
    chartdata["dd"] = {
        "kind": "series",
        "px": chartdata["eq"]["px"],
        "py": [round(P["t"] + (yhi2 - u["v"]) / (yhi2 - ylo2) * ph, 1) for u in uw],
        "label": [u["t"].strftime("%Y-%m-%d %H:%M") for u in uw],
        "text": [f'Drawdown {abs(u["v"])*100:.2f}%' for u in uw],
    }

    # ---- Mensual ----
    months = [{"label": k[2:], "v": v["abs"], "n": v["n"]}
              for k, v in m["monthly"].items()]
    svg_mo = svg_columns(months, chart_id="mo",
                         y_fmt=lambda v, d=1: f"{v:+.0f}", x_rotate=True)
    chartdata["mo"] = {
        "kind": "cols",
        "label": [k for k in m["monthly"]],
        "text": [f'{v["abs"]:+.2f} USDT<br>{v["n"]} operaciones'
                 for v in m["monthly"].values()],
    }

    # ---- Histograma ----
    hist = [{"label": f'{b["c"]*100:+.0f}%', "v": float(b["n"])} for b in m["hist"]]
    svg_hi = svg_columns(hist, chart_id="hi",
                         y_fmt=lambda v, d=0: f"{v:.0f}", x_rotate=True)
    chartdata["hi"] = {
        "kind": "cols",
        "label": [f'{b["a"]*100:+.1f}% a {b["b"]*100:+.1f}%' for b in m["hist"]],
        "text": [f'{b["n"]} operaciones' for b in m["hist"]],
    }

    # ---- Veredicto ----
    n_crit = sum(1 for c in checks if c["estado"] == "critical")
    n_warn = sum(1 for c in checks if c["estado"] == "warning")
    if n_crit:
        v_state, v_title = "critical", f"No hay ventaja demostrada ({n_crit} criterios fallan)"
        v_text = ("Al menos un criterio bloqueante no se cumple. Volver al diseno, "
                  "no reoptimizar sobre este mismo periodo: eso solo mide cuanto "
                  "sobreajustas.")
    elif n_warn:
        v_state, v_title = "warning", f"Resultado no concluyente ({n_warn} criterios por revisar)"
        v_text = ("Ningun criterio falla, pero hay avisos. Lee la nota de cada uno "
                  "antes de seguir al out-of-sample.")
    else:
        v_state, v_title = "good", "Todos los criterios se cumplen en este periodo"
        v_text = ("Esto demuestra que hubo ventaja en el periodo medido y que la "
                  "implementacion es correcta. No demuestra que la ventaja persista.")

    ev_cls = "up" if m["ev"] > 0 else "down"
    dd_cls = "" if m["max_dd"] < UMBRAL["drawdown"] else "down"

    # ---- Comparativa ----
    if bench:
        r_est = m["profit_pct"] / m["max_dd"] if m["max_dd"] else float("inf")
        if bench["dd_medible"]:
            bh_dd = f'{bench["max_dd"]*100:.1f}%'
            r_bh_txt = (f'{bench["profit_pct"]/bench["max_dd"]:.2f}'
                        if bench["max_dd"] else "&mdash;")
        else:
            bh_dd = '<span class="muted">no medible</span>'
            r_bh_txt = '<span class="muted">&mdash;</span>'
        comp = table(
            ["", "TrendPullbackV1", "Buy & hold BTC"],
            [["Profit total", fmt_pct(m["profit_pct"]), fmt_pct(bench["profit_pct"])],
             ["Max drawdown", f'{m["max_dd"]*100:.1f}%', bh_dd],
             ["Profit / drawdown",
              ("&mdash;" if r_est == float("inf") else f"{r_est:.2f}"), r_bh_txt],
             ["Operaciones", f'{m["n"]}', f'{bench["n"]}'],
             ["Tiempo expuesto", "parcial", "100%"]],
            numcols=(1, 2))
        if bench.get("desfasado"):
            comp += ('<p class="sub" style="margin-top:12px"><strong>AVISO: el '
                     'benchmark cubre un periodo distinto</strong> '
                     f'({esc(bench["periodo"])}) al de la estrategia. La '
                     'comparacion de esta tabla NO es valida. Regenera el '
                     'informe pasando el benchmark del mismo periodo con '
                     '<code>--benchmark</code>.</p>')
        if not bench["dd_medible"]:
            comp += ('<p class="sub" style="margin-top:12px">El buy &amp; hold cierra '
                     'una sola operacion, asi que su curva de capital tiene un unico '
                     'punto de cierre y el drawdown calculado saldria 0% <em>por '
                     'construccion</em>, no porque no lo haya tenido. Se marca como no '
                     'medible en vez de publicar un cero falso: para medirlo de verdad '
                     'hace falta la serie de precios, no la lista de operaciones.</p>')
    else:
        comp = ('<p class="sub">Sin benchmark cargado. Corre <code>make benchmark-in</code> '
                'y pasa el archivo con <code>--benchmark</code>. La regla del proyecto es '
                'comparar <em>siempre</em> contra comprar y mantener: una estrategia que no '
                'supera al benchmark en profit ni en profit/drawdown no justifica el riesgo '
                'operativo.</p>')

    # ---- Tablas de agrupacion ----
    pair_rows = [[esc(k), f'{v["n"]}', f'{v["win_rate"]*100:.0f}%', f'{v["abs"]:+.2f}']
                 for k, v in m["by_pair"].items()]
    exit_rows = [[esc(k), f'{v["n"]}', f'{v["win_rate"]*100:.0f}%', f'{v["abs"]:+.2f}']
                 for k, v in m["by_exit"].items()]

    check_rows = []
    for c in checks:
        nota = f'<br><span class="muted">{esc(c["nota"])}</span>' if c["nota"] else ""
        check_rows.append([esc(c["label"]) + nota, c["valor"], esc(c["umbral"]),
                           badge(c["estado"])])

    mo_rows = [[esc(k), f'{v["n"]}', f'{v["abs"]:+.2f}'] for k, v in m["monthly"].items()]
    eq_rows = [[esc(e["t"].strftime("%Y-%m-%d %H:%M")), fmt_pct(e["pct"], 2),
                f'{e["eq"]:.2f}'] for e in m["equity"]]
    hi_rows = [[f'{b["a"]*100:+.1f}% a {b["b"]*100:+.1f}%', f'{b["n"]}'] for b in m["hist"]]

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Analisis de backtest · {esc(meta['strategy'])} · freqtrade-quant</title>
<meta name="description" content="Metricas, curva de capital y semaforo de umbrales del backtest de {esc(meta['strategy'])}.">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <h1>Analisis de backtest</h1>
    <p class="sub">{esc(meta['strategy'])} · {esc(meta['label'])} · timeframe {esc(m['timeframe'])}
      · generado {esc(meta['generated'])}</p>
  </div>
  <button id="theme" type="button">Tema oscuro</button>
</header>

<div class="banner {v_state}">
  <strong>{esc(v_title)}</strong>
  {esc(v_text)}
</div>

<div class="grid3">
  <div class="card hero">
    <p class="label">Valor esperado por operacion, despues de comisiones</p>
    <div class="value {ev_cls}">{m['ev']:+.4f}<span class="unit">USDT</span></div>
    <p class="why">Es la unica metrica que decide si existe una ventaja. Con operaciones
      de {esc(m['stake'])} USDT, la comision de ida y vuelta cuesta ~0.02 USDT:
      el valor esperado tiene que ser comodamente superior a eso.
      Media de {m['n']} operaciones.</p>
  </div>
  <div class="card">
    <h2>Periodo</h2>
    <p class="sub">
      {esc(m['first'].strftime('%Y-%m-%d'))} &rarr; {esc(m['last'].strftime('%Y-%m-%d'))}<br>
      {m['span_days']} dias · {m['trading_days']} con cierres ({m["trading_days"]/max(m["calendar_days"],1)*100:.0f}%)<br>
      {m['trades_per_day']:.2f} operaciones/dia<br>
      duracion media {m['avg_mins']/60:.1f} h<br>
      capital inicial {m['start_bal']:.2f} USDT
    </p>
  </div>
</div>

<div class="tiles">
  {tile("Operaciones", str(m['n']), f"{m['wins']} ganadas / {m['losses']} perdidas")}
  {tile("Win rate", f"{m['win_rate']*100:.1f}%", "no mirar sin la perdida media")}
  {tile("Profit total", fmt_pct(m['profit_pct']), f"{m['profit_abs']:+.2f} USDT")}
  {tile("Max drawdown", f"{m['max_dd']*100:.1f}%", f"{m['max_dd_abs']:.2f} USDT", dd_cls)}
  {tile("Profit factor", ("inf" if m['profit_factor']==float('inf') else f"{m['profit_factor']:.2f}"), "ganancias / perdidas brutas")}
  {tile("Sharpe", f"{m['sharpe']:.2f}", "diario sobre el calendario completo")}
  {tile("Sortino", f"{m['sortino']:.2f}", "idem, solo penaliza caidas")}
  {tile("CAGR", (fmt_pct(m['cagr']) if m['cagr'] is not None else "n/d"), "extrapolado del periodo")}
</div>

<div class="tiles">
  {tile("Ganancia media", f"{m['avg_win']:+.3f}", "USDT por operacion ganadora")}
  {tile("Perdida media", f"{m['avg_loss']:+.3f}", "USDT por operacion perdedora")}
  {tile("Mejor operacion", f"{m['best']['abs']:+.2f}", esc(m['best']['pair']))}
  {tile("Peor operacion", f"{m['worst']['abs']:+.2f}", esc(m['worst']['pair']))}
</div>

<div class="card">
  <h2>Semaforo contra los umbrales</h2>
  <p class="sub">Umbrales de <code>docs/VALIDACION.md</code>. Un solo FALLA es motivo
    suficiente para no avanzar.</p>
  {table(["Criterio", "Valor", "Umbral", "Estado"], check_rows, numcols=(1,))}
</div>

<div class="card">
  <h2>Curva de rentabilidad acumulada</h2>
  <p class="sub">Rentabilidad sobre el capital inicial, operacion a operacion.
    El buy &amp; hold se dibuja como linea de referencia en su valor final: desde las
    operaciones exportadas no se puede reconstruir su curva intermedia.</p>
  {svg_eq}
  <div class="legend">
    <span><i class="key" style="background:var(--s1)"></i>TrendPullbackV1</span>
    {'<span><i class="key" style="background:var(--s2)"></i>Buy &amp; hold BTC (final)</span>' if bench else ''}
  </div>
  <details><summary>Ver los datos en tabla</summary>
    {table(["Cierre", "Rentabilidad", "Capital USDT"], eq_rows, numcols=(1,2))}
  </details>
</div>

<div class="card">
  <h2>Drawdown bajo el agua</h2>
  <p class="sub">Distancia al maximo historico de capital. Es lo que de verdad
    determina si podrias operar el sistema sin apagarlo en el peor momento.</p>
  {svg_dd}
  <details><summary>Ver los datos en tabla</summary>
    {table(["Cierre", "Drawdown"], [[esc(u["t"].strftime("%Y-%m-%d %H:%M")), f'{abs(u["dd"])*100:.2f}%'] for u in m["underwater"]], numcols=(1,))}
  </details>
</div>

<div class="card">
  <h2>Resultado por mes</h2>
  <p class="sub">Revela si la ganancia viene de dos meses buenos y diez planos.
    Sin el mejor mes ({esc(m['best_month'])}) el total queda en
    <strong>{m['sin_mejor_mes']:+.2f} USDT</strong>.</p>
  {svg_mo}
  <div class="legend">
    <span><i class="key sq" style="background:var(--pos)"></i>Mes positivo</span>
    <span><i class="key sq" style="background:var(--neg)"></i>Mes negativo</span>
  </div>
  <details><summary>Ver los datos en tabla</summary>
    {table(["Mes", "Operaciones", "P/L USDT"], mo_rows, numcols=(1,2))}
  </details>
</div>

<div class="card">
  <h2>Distribucion del resultado por operacion</h2>
  <p class="sub">Cuantas operaciones caen en cada rango de rentabilidad.
    Una cola izquierda larga significa que las perdidas corren mas que las ganancias,
    aunque el win rate parezca bueno.</p>
  {svg_hi}
  <div class="legend">
    <span><i class="key sq" style="background:var(--pos)"></i>Ganancia</span>
    <span><i class="key sq" style="background:var(--neg)"></i>Perdida</span>
  </div>
  <details><summary>Ver los datos en tabla</summary>
    {table(["Rango", "Operaciones"], hi_rows, numcols=(1,))}
  </details>
</div>

<div class="card">
  <h2>Comparativa contra comprar y mantener</h2>
  {comp}
</div>

<div class="card">
  <h2>Por par</h2>
  {table(["Par", "Operaciones", "Win rate", "P/L USDT"], pair_rows, numcols=(1,2,3))}
</div>

<div class="card">
  <h2>Por motivo de salida</h2>
  <p class="sub">La pregunta clave: ¿de donde sale el dinero? Si casi todo el profit
    viene de <code>roi</code> y las salidas por senal son todas perdidas, la senal de
    salida no aporta y la estrategia es en realidad "comprar y esperar el ROI".</p>
  {table(["Motivo", "Operaciones", "Win rate", "P/L USDT"], exit_rows, numcols=(1,2,3))}
</div>

<footer>
  <p>Generado por <code>scripts/report.py</code> desde
    <code>{esc(meta['source'])}</code>. Todas las metricas se calculan desde la lista
    de operaciones exportada, no se leen de los campos agregados del JSON.</p>
  <p>El drawdown se calcula sobre la curva de capital en los <em>cierres</em> de
    operacion, igual que lo hace Freqtrade. Las caidas que ocurren con una posicion
    abierta y que luego se recuperan antes de cerrar no aparecen: el drawdown real
    vivido es algo mayor que el que se muestra aqui.</p>
  <p>Freqtrade no simula slippage: asume llenado al precio de la vela, asi que este
    resultado es optimista. Repite con <code>make stress</code> (comisiones al 0.15% y
    0.2% por lado) antes de darlo por bueno.
    Un backtest validado no predice el futuro.</p>
  <p><a href="https://github.com/Maykhol10/freqtrade-quant">freqtrade-quant</a> ·
    Documentacion de investigacion, no asesoria financiera.</p>
</footer>

</div>
<div id="tip" role="status" aria-live="polite"></div>
<script type="application/json" id="chartdata">{json.dumps(chartdata)}</script>
<script>{JS}</script>
</body>
</html>
"""


# ================================================================ #
#  main
# ================================================================ #

def main():
    ap = argparse.ArgumentParser(
        description="Dashboard HTML desde los resultados de backtest de Freqtrade.")
    ap.add_argument("--in", dest="src",
                    help="Resultado de backtest (.zip o .json). Por defecto se busca "
                         "el mas reciente que contenga --strategy")
    ap.add_argument("--strategy", default=None,
                    help="Estrategia a analizar (si el resultado tiene varias)")
    ap.add_argument("--benchmark",
                    help="Resultado del benchmark (.zip o .json)")
    ap.add_argument("--benchmark-strategy", default="BuyAndHoldBTC",
                    help="Estrategia del benchmark (por defecto BuyAndHoldBTC)")
    ap.add_argument("--benchmark-drawdown", type=float, default=None,
                    help="Max drawdown REAL del benchmark en %% (ej: 76.6). El "
                         "calculado desde operaciones es 0 por construccion "
                         "cuando el benchmark cierra una sola operacion.")
    ap.add_argument("--no-benchmark", action="store_true",
                    help="No buscar benchmark automaticamente")
    ap.add_argument("--out", default="docs/report.html", help="HTML de salida")
    ap.add_argument("--label", default="", help="Etiqueta del periodo, ej: 'In-sample 2023-2024'")
    ap.add_argument("--oos", action="store_true",
                    help="Periodo out-of-sample: baja el umbral de operaciones a 50")
    ap.add_argument("--starting-balance", type=float, default=None,
                    help="Capital inicial si el JSON no lo trae")
    args = ap.parse_args()

    src = args.src or find_result(args.strategy)
    if not src:
        raise SystemExit(
            f"ERROR: no hay resultados de backtest en {RESULTS_DIR}/.\n"
            "       Corre primero:  make backtest-in")
    if not os.path.exists(src):
        raise SystemExit(f"ERROR: no existe {src}")

    name, result = load_result(src, args.strategy)
    m = compute(result, args.starting_balance)

    # Benchmark: el explicito, o el resultado mas reciente que lo contenga.
    # Freqtrade ignora --export-filename y nombra por fecha, asi que se busca
    # por contenido.
    bench_src = args.benchmark
    if not bench_src and not args.no_benchmark:
        bench_src = find_result(args.benchmark_strategy)
        if bench_src == src:
            bench_src = None

    bench = None
    if bench_src:
        if not os.path.exists(bench_src):
            raise SystemExit(f"ERROR: no existe el benchmark {bench_src}")
        _, bres = load_result(bench_src, args.benchmark_strategy)
        bm = compute(bres, args.starting_balance)

        # Salvaguarda: comparar periodos distintos invalida la comparacion.
        # El benchmark se busca automaticamente por nombre de estrategia, asi
        # que es facil agarrar el de otro periodo sin darse cuenta -- y la tabla
        # saldria perfectamente creible con los numeros equivocados.
        desfase = max(abs((bm["open_first"] - m["open_first"]).days),
                      abs((bm["last"] - m["last"]).days))
        if desfase > max(m["span_days"] * 0.10, 30):
            print(f"  AVISO: el benchmark cubre "
                  f"{bm['open_first'].date()} -> {bm['last'].date()} y la "
                  f"estrategia {m['open_first'].date()} -> {m['last'].date()}",
                  file=sys.stderr)
            print(f"         desfase de {desfase} dias: la comparacion no es valida.",
                  file=sys.stderr)
            print(f"         Pasa el benchmark correcto con --benchmark <archivo>.",
                  file=sys.stderr)
            bench_desfasado = True
        else:
            bench_desfasado = False
        bench = {
            "profit_pct": bm["profit_pct"],
            "max_dd": bm["max_dd"],
            "n": bm["n"],
            # Con muy pocas operaciones la curva de capital tiene demasiados pocos
            # puntos de cierre para que el drawdown signifique algo.
            "dd_medible": bm["n"] >= 5,
            "desfasado": bench_desfasado,
            "periodo": f"{bm['open_first'].date()} -> {bm['last'].date()}",
        }
        if args.benchmark_drawdown is not None:
            bench["max_dd"] = args.benchmark_drawdown / 100.0
            bench["dd_medible"] = True
            bench["dd_externo"] = True

    checks = evaluate(m, bench, args.oos)

    label = args.label or ("Out-of-sample" if args.oos else "In-sample")
    meta = {
        "strategy": name,
        "label": label,
        "source": src,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(m, bench, checks, meta))

    n_crit = sum(1 for c in checks if c["estado"] == "critical")
    n_warn = sum(1 for c in checks if c["estado"] == "warning")
    size = os.path.getsize(args.out) / 1024

    print(f"Escrito {args.out}  ({size:.0f} KB)")
    print(f"  fuente:       {src}")
    print(f"  estrategia:   {name}")
    if bench_src:
        print(f"  benchmark:    {bench_src}")
    print(f"  periodo:      {m['first'].date()} -> {m['last'].date()}  ({m['span_days']} dias)")
    print(f"  operaciones:  {m['n']}  ({m['wins']}G / {m['losses']}P)")
    print(f"  EV/operacion: {m['ev']:+.4f} USDT")
    print(f"  profit:       {m['profit_pct']*100:+.2f}%  ({m['profit_abs']:+.2f} USDT)")
    print(f"  max drawdown: {m['max_dd']*100:.1f}%")
    print(f"  semaforo:     {len(checks)-n_crit-n_warn} PASA / {n_warn} REVISAR / {n_crit} FALLA")

    # Codigo de salida util en scripts: 1 si algun criterio bloqueante falla
    sys.exit(1 if n_crit else 0)


if __name__ == "__main__":
    main()
