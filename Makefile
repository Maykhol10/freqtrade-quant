# Atajos para los comandos de docs/COMANDOS.md
# Uso:  make help

FT      := docker compose run --rm freqtrade
CONFIG  := user_data/config.json
STRAT   := TrendPullbackV1
PAIRS   := BTC/USDT ETH/USDT

IN_SAMPLE  := 20230201-20250101
OUT_SAMPLE := 20250101-

COMMON := --config $(CONFIG) --strategy $(STRAT) --enable-protections --cache none

# report.py usa solo la libreria estandar: corre con el python del sistema,
# no necesita el contenedor ni pip install
PY := python3

.PHONY: help install preflight verify pull download download-detail \
        audit lookahead recursive backtest-in backtest-out stress \
        benchmark-in benchmark-out walkforward analysis hyperopt \
        dashboard report-html report-html-oos \
        up down logs restart report watchdog backup \
        cron-install cron-remove cron-show systemd-install clean-db

help:
	@echo "Servidor"
	@echo "  make install          Bootstrap: Docker, .env, permisos, imagen"
	@echo "  make verify           Comprueba que las estrategias cargan"
	@echo "  make preflight        12 comprobaciones antes de arrancar"
	@echo "  make cron-install     Resumen diario + vigilancia + respaldo"
	@echo "  make systemd-install  Unidad systemd (opcional)"
	@echo ""
	@echo "Datos"
	@echo "  make download         Descarga 1h y 4h desde 2023-01-01"
	@echo "  make download-detail  Descarga 5m (para --timeframe-detail)"
	@echo ""
	@echo "Auditoria  (BLOQUEANTE: correr antes de cualquier backtest)"
	@echo "  make audit            lookahead-analysis + recursive-analysis"
	@echo ""
	@echo "Validacion"
	@echo "  make backtest-in      In-sample  $(IN_SAMPLE)"
	@echo "  make stress           Backtest con fee 0.1% / 0.15% / 0.2%"
	@echo "  make benchmark-in     Buy & hold BTC, mismo periodo"
	@echo "  make analysis         Desglose por exit_tag"
	@echo "  make hyperopt         Hyperopt (solo in-sample, 3 parametros)"
	@echo "  make dashboard        Dashboard HTML -> docs/report.html"
	@echo "  make backtest-out     Out-of-sample $(OUT_SAMPLE)  <- UNA sola vez"
	@echo "  make benchmark-out    Buy & hold BTC, out-of-sample"
	@echo "  make walkforward      6 ventanas semestrales"
	@echo ""
	@echo "Dry-run"
	@echo "  make up / down / logs / restart"
	@echo "  make report           Resumen diario a Telegram (manual)"
	@echo "  make watchdog         Vigilancia a mano"
	@echo "  make backup           Respaldo a mano"

# ------------------------------------------------------------------ #
#  Servidor
# ------------------------------------------------------------------ #
install:
	./scripts/install.sh

preflight:
	./scripts/preflight.sh

verify:
	@echo "=== estrategias que Freqtrade consigue importar ==="
	$(FT) list-strategies --config $(CONFIG)
	@echo "=== config.json aceptada por Freqtrade? ==="
	@$(FT) show-config --config $(CONFIG) >/dev/null && echo "  OK" || echo "  RECHAZADA"

cron-install:
	./scripts/cron-install.sh

cron-remove:
	./scripts/cron-install.sh --remove

cron-show:
	./scripts/cron-install.sh --show

systemd-install:
	sudo cp systemd/freqtrade-quant.service /etc/systemd/system/
	sudo sed -i "s/__USER__/$(USER)/;s#__ROOT__#$(CURDIR)#" \
		/etc/systemd/system/freqtrade-quant.service
	sudo systemctl daemon-reload
	@echo "Instalada. Activar con: sudo systemctl enable --now freqtrade-quant"

pull:
	docker compose pull

download:
	$(FT) download-data --config $(CONFIG) --exchange binance --trading-mode spot \
		--pairs $(PAIRS) --timeframes 1h 4h --timerange 20230101-
	$(FT) list-data --config $(CONFIG) --show-timerange

download-detail:
	$(FT) download-data --config $(CONFIG) --exchange binance --trading-mode spot \
		--pairs $(PAIRS) --timeframes 5m --timerange 20230101-

# ------------------------------------------------------------------ #
#  Auditoria anti-sesgo
# ------------------------------------------------------------------ #
audit: lookahead recursive

lookahead:
	@echo "=== lookahead-analysis: se espera biased_entry/biased_exit = False ==="
	$(FT) lookahead-analysis --config $(CONFIG) --strategy $(STRAT) \
		--timerange $(IN_SAMPLE) --cache none

recursive:
	@echo "=== recursive-analysis: se espera desvio < 0.1% a 799/999 velas ==="
	$(FT) recursive-analysis --config $(CONFIG) --strategy $(STRAT) \
		--timerange $(IN_SAMPLE) --startup-candle 199 399 799 999

# ------------------------------------------------------------------ #
#  Backtests
# ------------------------------------------------------------------ #
backtest-in:
	$(FT) backtesting $(COMMON) --timerange $(IN_SAMPLE) \
		--timeframe-detail 5m --breakdown month \
		--export trades --export-filename user_data/backtest_results/in_sample.json

backtest-out:
	@echo ">>> OUT-OF-SAMPLE. No ajustar nada despues de ver esto. <<<"
	$(FT) backtesting $(COMMON) --timerange $(OUT_SAMPLE) \
		--timeframe-detail 5m --breakdown month \
		--export trades --export-filename user_data/backtest_results/out_of_sample.json

stress:
	@for FEE in 0.001 0.0015 0.002; do \
		echo "===== fee = $$FEE por lado ====="; \
		$(FT) backtesting $(COMMON) --timerange $(IN_SAMPLE) \
			--timeframe-detail 5m --fee $$FEE 2>/dev/null \
			| grep -E 'Total/Daily Avg Trades|Total profit %|Max % of account|Sharpe|Sortino|profit factor'; \
	done

benchmark-in:
	$(FT) backtesting --config $(CONFIG) --strategy BuyAndHoldBTC \
		--pairs BTC/USDT --max-open-trades 1 --stake-amount unlimited \
		--timerange $(IN_SAMPLE) --cache none \
		--export trades --export-filename user_data/backtest_results/buyhold_in.json

benchmark-out:
	$(FT) backtesting --config $(CONFIG) --strategy BuyAndHoldBTC \
		--pairs BTC/USDT --max-open-trades 1 --stake-amount unlimited \
		--timerange $(OUT_SAMPLE) --cache none \
		--export trades --export-filename user_data/backtest_results/buyhold_out.json

walkforward:
	@for R in 20230201-20230801 20230801-20240201 20240201-20240801 \
	          20240801-20250201 20250201-20250801 20250801-; do \
		echo "########## $$R ##########"; \
		$(FT) backtesting $(COMMON) --timerange $$R --timeframe-detail 5m 2>/dev/null \
			| grep -E 'Total/Daily Avg Trades|Total profit %|Max % of account|Sharpe|Sortino'; \
	done

analysis:
	$(FT) backtesting-analysis --config $(CONFIG) \
		--analysis-groups 0 1 2 --indicators rsi atr_pct uptrend_4h

# ------------------------------------------------------------------ #
#  Dashboard HTML (solo libreria estandar de Python, sin pip)
#  Devuelve codigo 1 si algun criterio bloqueante falla, asi que sirve en CI.
# ------------------------------------------------------------------ #
dashboard: report-html

report-html:
	$(PY) scripts/report.py \
		--in user_data/backtest_results/in_sample.json \
		--benchmark user_data/backtest_results/buyhold_in.json \
		--out docs/report.html \
		--label "In-sample $(IN_SAMPLE)"

report-html-oos:
	$(PY) scripts/report.py --oos \
		--in user_data/backtest_results/out_of_sample.json \
		--benchmark user_data/backtest_results/buyhold_out.json \
		--out docs/report-oos.html \
		--label "Out-of-sample $(OUT_SAMPLE)"

hyperopt:
	@echo ">>> Riesgo de sobreajuste. Solo in-sample. Leer docs/COMANDOS.md seccion 6. <<<"
	$(FT) hyperopt $(COMMON) --hyperopt-loss SharpeHyperOptLossDaily \
		--spaces buy sell --epochs 150 --timerange $(IN_SAMPLE) \
		--timeframe-detail 5m --min-trades 100 -j 2

# ------------------------------------------------------------------ #
#  Dry-run
# ------------------------------------------------------------------ #
up:
	docker compose up -d
	docker compose logs -f --tail 50

down:
	docker compose down

logs:
	docker compose logs -f --tail 100

restart:
	docker compose restart

report:
	./scripts/daily_report.sh

watchdog:
	./scripts/watchdog.sh

backup:
	./scripts/backup.sh

clean-db:
	@echo "Esto borra el historial del dry-run. Ctrl-C para abortar."
	@sleep 5
	docker compose down
	rm -f user_data/tradesv3.dryrun.sqlite
