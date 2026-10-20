<#
.SYNOPSIS
  Equivalente del Makefile para Windows sin Docker, WSL ni servidor.

.DESCRIPTION
  Corre Freqtrade desde un entorno virtual local. Sirve para los pasos que
  deciden si existe una ventaja -- descargar datos, auditar sesgos, backtestear
  y generar el dashboard -- sin necesidad de una VM.

  Lo que NO sustituye: el dry-run de 3-4 semanas de la checklist, que necesita
  una maquina que no se apague. Para eso hace falta el servidor.

.EXAMPLE
  .\scripts\local.ps1 setup        # crea .venv e instala freqtrade
  .\scripts\local.ps1 download     # velas 1h + 4h desde 2023-01-01
  .\scripts\local.ps1 audit        # lookahead + recursive   <- BLOQUEANTE
  .\scripts\local.ps1 backtest
  .\scripts\local.ps1 benchmark
  .\scripts\local.ps1 dashboard    # -> docs/report.html
  .\scripts\local.ps1 all          # download + audit + backtest + benchmark + dashboard
  .\scripts\local.ps1 trade        # dry-run local, FreqUI en localhost:8080
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'verify', 'download', 'download-detail', 'audit',
                 'backtest', 'backtest-oos', 'benchmark', 'benchmark-oos',
                 'stress', 'analysis', 'dashboard', 'walkforward',
                 'trade', 'all', 'help')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Config     = 'user_data/config.json'
$Strategy   = 'TrendPullbackV1'
$InSample   = '20230201-20250101'
$OutSample  = '20250101-'
$Pairs      = @('BTC/USDT', 'ETH/USDT')

$FT = Join-Path $Root '.venv\Scripts\freqtrade.exe'
$PY = Join-Path $Root '.venv\Scripts\python.exe'

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  !   $msg" -ForegroundColor Yellow }

function Need-Venv {
    if (-not (Test-Path $FT)) {
        Write-Host "Falta el entorno virtual. Corre primero:" -ForegroundColor Red
        Write-Host "  .\scripts\local.ps1 setup"
        exit 1
    }
}

function Rand-Hex([int]$n) {
    -join (1..$n | ForEach-Object { '{0:x}' -f (Get-Random -Minimum 0 -Maximum 16) })
}

# En el servidor los secretos los inyecta docker compose via env_file. Aqui no hay
# contenedor, asi que hay que cargar .env a mano. Ademas el schema de Freqtrade
# exige que telegram.token y chat_id EXISTAN aunque enabled sea false, asi que si
# estan vacios apagamos Telegram en vez de dejar que la validacion falle.
function Load-Env {
    $envFile = Join-Path $Root '.env'
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
                $name = $Matches[1]
                $value = $Matches[2].Trim()
                if ($value) { Set-Item -Path "env:$name" -Value $value }
            }
        }
    }
    if (-not $env:FREQTRADE__TELEGRAM__TOKEN -or -not $env:FREQTRADE__TELEGRAM__CHAT_ID) {
        $env:FREQTRADE__TELEGRAM__ENABLED = 'false'
    }
    if (-not $env:FREQTRADE__API_SERVER__PASSWORD) {
        $env:FREQTRADE__API_SERVER__USERNAME = 'freq'
        $env:FREQTRADE__API_SERVER__PASSWORD = Rand-Hex 24
    }
    if (-not $env:FREQTRADE__API_SERVER__JWT_SECRET_KEY) {
        $env:FREQTRADE__API_SERVER__JWT_SECRET_KEY = Rand-Hex 48
    }
    $env:PYTHONIOENCODING = 'utf-8'
}

Load-Env

# ------------------------------------------------------------------ #
switch ($Task) {

'help' {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
}

'setup' {
    Step 'Entorno virtual'
    if (-not (Test-Path '.venv')) {
        python -m venv .venv
        Ok '.venv creado'
    } else { Ok '.venv ya existe' }

    Step 'Instalando freqtrade (tarda varios minutos)'
    & $PY -m pip install --upgrade pip
    & $PY -m pip install freqtrade

    Step 'Verificando'
    & $FT --version
    Write-Host ""
    Ok 'Listo. Siguiente:  .\scripts\local.ps1 download'
}

'verify' {
    Need-Venv
    Step 'Estrategias que Freqtrade consigue importar'
    & $FT list-strategies --config $Config
    Step 'config.json aceptada?'
    & $FT show-config --config $Config | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok 'config.json valida' } else { Warn 'config.json rechazada' }
}

'download' {
    Need-Venv
    Step 'Descargando velas 1h y 4h desde 2023-01-01'
    & $FT download-data --config $Config --exchange binance --trading-mode spot `
        --pairs $Pairs --timeframes 1h 4h --timerange 20230101-
    Step 'Que quedo descargado'
    & $FT list-data --config $Config --show-timerange
}

'download-detail' {
    Need-Venv
    Step 'Descargando velas de 5m (simula stops dentro de la vela de 1h)'
    & $FT download-data --config $Config --exchange binance --trading-mode spot `
        --pairs $Pairs --timeframes 5m --timerange 20230101-
}

'audit' {
    Need-Venv
    Step 'lookahead-analysis  -- se espera biased_entry/biased_exit = False'
    # lookahead-analysis gestiona su propia cache: --cache none da
    # "unrecognized arguments". Solo backtesting lo acepta.
    & $FT lookahead-analysis --config $Config --strategy $Strategy `
        --timerange $InSample
    Step 'recursive-analysis  -- se espera desvio < 0.1% a 799/999 velas'
    & $FT recursive-analysis --config $Config --strategy $Strategy `
        --timerange $InSample --startup-candle 199 399 799 999
    Write-Host ""
    Warn 'Si algo sale biased = True, PARA. La estrategia lee el futuro.'
}

'backtest' {
    Need-Venv
    $detail = @()
    if (Test-Path 'user_data/data/binance') {
        $has5m = Get-ChildItem 'user_data/data/binance' -Filter '*5m*' -ErrorAction SilentlyContinue
        if ($has5m) { $detail = @('--timeframe-detail', '5m') }
        else { Warn 'sin datos de 5m: los stops saldran optimistas (corre download-detail)' }
    }
    Step "Backtest in-sample $InSample"
    & $FT backtesting --config $Config --strategy $Strategy `
        --timerange $InSample @detail --breakdown month `
        --enable-protections --cache none `
        --export trades
}

'backtest-oos' {
    Need-Venv
    Write-Host ""
    Warn 'OUT-OF-SAMPLE: no ajustes nada despues de ver esto.'
    Step "Backtest out-of-sample $OutSample"
    & $FT backtesting --config $Config --strategy $Strategy `
        --timerange $OutSample --breakdown month --enable-protections --cache none `
        --export trades
}

'benchmark' {
    Need-Venv
    Step 'Comprar y mantener BTC, mismo periodo'
    & $FT backtesting --config $Config --strategy BuyAndHoldBTC `
        --pairs BTC/USDT --max-open-trades 1 --stake-amount unlimited `
        --timerange $InSample --cache none `
        --export trades
}

'benchmark-oos' {
    Need-Venv
    Step 'Comprar y mantener BTC, out-of-sample'
    & $FT backtesting --config $Config --strategy BuyAndHoldBTC `
        --pairs BTC/USDT --max-open-trades 1 --stake-amount unlimited `
        --timerange $OutSample --cache none `
        --export trades
}

'stress' {
    Need-Venv
    foreach ($fee in @('0.001', '0.0015', '0.002')) {
        Step "fee = $fee por lado"
        & $FT backtesting --config $Config --strategy $Strategy `
            --timerange $InSample --enable-protections --cache none --fee $fee |
            Select-String -Pattern 'Total/Daily Avg Trades|Total profit %|Max % of account|Sharpe|Sortino|profit factor'
    }
    Write-Host ""
    Warn 'Si la ventaja desaparece a 0.0015, no hay ventaja: era ruido dentro del costo.'
}

'analysis' {
    Need-Venv
    Step 'De que motivo de salida sale el dinero'
    & $FT backtesting-analysis --config $Config `
        --analysis-groups 0 1 2 --indicators rsi atr_pct uptrend_4h
}

'walkforward' {
    Need-Venv
    foreach ($r in @('20230201-20230801','20230801-20240201','20240201-20240801',
                     '20240801-20250201','20250201-20250801','20250801-')) {
        Step "ventana $r"
        & $FT backtesting --config $Config --strategy $Strategy `
            --timerange $r --enable-protections --cache none |
            Select-String -Pattern 'Total/Daily Avg Trades|Total profit %|Max % of account|Sharpe|Sortino'
    }
    Write-Host ""
    Warn 'Buscas consistencia, no que todas sean positivas.'
}

'dashboard' {
    if (-not (Get-ChildItem 'user_data/backtest_results' -Filter '*.zip' -ErrorAction SilentlyContinue)) {
        Write-Host "Falta el backtest. Corre primero:" -ForegroundColor Red
        Write-Host "  .\scripts\local.ps1 backtest"
        exit 1
    }
    Step 'Generando dashboard'
    # report.py localiza los resultados por nombre de estrategia: Freqtrade
    # ignora --export-filename y nombra los archivos por fecha.
    $py = if (Test-Path $PY) { $PY } else { 'python' }
    & $py scripts/report.py --strategy $Strategy `
        --out docs/report.html --label "In-sample $InSample"
    $code = $LASTEXITCODE
    Write-Host ""
    Ok "Abrelo con:  start docs\report.html"
    if ($code -ne 0) { Warn 'Algun criterio bloqueante falla: revisa el semaforo.' }
}

'trade' {
    Need-Venv
    Step 'Dry-run local'
    Write-Host "  FreqUI: http://localhost:8080  (usuario y clave de .env)"
    Write-Host "  Detener: Ctrl-C"
    Write-Host ""
    Warn 'Esto muere cuando apagas o suspendes el PC.'
    Warn 'Las 3-4 semanas seguidas de la checklist necesitan el servidor.'
    Write-Host ""
    & $FT trade --config $Config --strategy $Strategy `
        --db-url sqlite:///user_data/tradesv3.dryrun.sqlite `
        --logfile user_data/logs/freqtrade.log
}

'all' {
    Need-Venv
    & $PSCommandPath download
    & $PSCommandPath audit
    & $PSCommandPath backtest
    & $PSCommandPath benchmark
    & $PSCommandPath dashboard
}

}
