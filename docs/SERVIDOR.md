# Despliegue en el servidor

Guía para dejar el bot corriendo en una VM Linux de Azure. Pensada para seguirse de arriba abajo la primera vez.

---

## Resumen: tres comandos

```bash
git clone https://github.com/Maykhol10/freqtrade-quant.git /opt/freqtrade-quant
cd /opt/freqtrade-quant && ./scripts/install.sh
make download && make audit
```

El resto de este documento explica cada parte y qué hacer cuando algo falla.

---

## 1. La VM

| | Mínimo | Recomendado | Por qué |
|---|---|---|---|
| Tamaño Azure | B1s (1 vCPU, 1 GB) | **B2s** (2 vCPU, 4 GB) | Hyperopt con `-j 2` necesita 2 núcleos y se come la RAM |
| Disco | 30 GB SSD | 30 GB SSD | Los datos de 5m de 3 años pesan ~2 GB |
| SO | Ubuntu 22.04 LTS | **Ubuntu 24.04 LTS** | `docker-compose-v2` está en los repos |
| IP pública | Dinámica | **Estática** | La restricción por IP de la API key de Binance se rompe si cambia |

> Con B1s (1 GB de RAM) el bot funciona en dry-run, pero `make hyperopt` muere por falta de memoria. Si te quedas en B1s, añade swap (sección 3) y usa `-j 1`.

### Grupo de seguridad de red (NSG)

Solo una regla de entrada:

| Prioridad | Puerto | Origen | Acción |
|---|---|---|---|
| 300 | 22 (SSH) | **tu IP**, no `Any` | Permitir |
| — | todo lo demás | — | Denegar (por defecto) |

**El puerto 8080 no se abre nunca.** La API queda en `127.0.0.1` y se accede por túnel SSH (sección 7). Un FreqUI expuesto a internet con usuario y contraseña es una invitación.

---

## 2. Instalación

```bash
# Directorio del proyecto
sudo mkdir -p /opt/freqtrade-quant
sudo chown -R "$USER:$USER" /opt/freqtrade-quant
cd /opt/freqtrade-quant

git clone https://github.com/Maykhol10/freqtrade-quant.git .

# Bootstrap: Docker, .env con secretos generados, permisos, imagen, verificación
./scripts/install.sh
```

`install.sh` es idempotente — puedes correrlo varias veces. Hace:

1. Instala `docker-ce` + plugin compose desde el repositorio oficial, más `jq`, `curl`, `openssl`, `git`.
2. Crea `.env` desde la plantilla y **genera** el password de la API, el `JWT_SECRET_KEY` y el `WS_TOKEN` con `openssl rand`. Si `.env` ya existe, hace copia de seguridad y solo rellena las claves vacías.
3. Pregunta el token y el chat_id de Telegram (o los tomas de `--telegram-token` / `--chat-id`).
4. Ajusta `user_data` al uid 1000 del contenedor.
5. Descarga la imagen y **verifica que las estrategias importan de verdad** con `freqtrade list-strategies`. Esta es la primera validación real: si `TrendPullbackV1` no carga, el script falla aquí y no más adelante con un error confuso.

Modo desatendido:

```bash
./scripts/install.sh --telegram-token 123456:ABC... --chat-id 987654321
```

> Si el script te añade al grupo `docker`, se detiene y te pide cerrar sesión. Es necesario: la pertenencia a un grupo solo se aplica en una sesión nueva. Vuelve a entrar y repite.

---

## 3. Ajustes del sistema

### Zona horaria

```bash
sudo timedatectl set-timezone America/Lima
timedatectl    # NTPSynchronized debe decir yes
```

El reloj importa de verdad: Binance firma las peticiones con una marca de tiempo y rechaza las que se desvían más de unos segundos. `preflight.sh` lo comprueba.

### Swap (obligatorio en B1s, recomendado en B2s)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

Sin swap, `make hyperopt` y los backtests con `--timeframe-detail 5m` pueden morir por OOM a media ejecución y dejarte sin resultado tras 40 minutos.

### Actualizaciones de seguridad desatendidas

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 4. Validación antes de arrancar

**Este es el orden, y no es negociable.** La auditoría va antes de cualquier número de rentabilidad.

```bash
make download          # 1h + 4h desde 2023-01-01        ~5 min
make download-detail   # 5m para simular stops           ~15 min
make audit             # lookahead + recursive  <- BLOQUEANTE
```

Qué esperar de `make audit`:

| Comprobación | Resultado aceptable | Si falla |
|---|---|---|
| `lookahead-analysis` | `biased_entry: False` y `biased_exit: False` en todo | La estrategia lee el futuro. **Parar.** Revisar `.shift()`, `max()/min()` globales, informatives sin merge |
| `recursive-analysis` | desvío < 0.1% a 799/999 velas | Subir `startup_candle_count` en la estrategia y repetir |

Solo cuando salga limpio:

```bash
make backtest-in       # in-sample 2023-02 -> 2024-12
make stress            # fee 0.1% / 0.15% / 0.2%   <- BLOQUEANTE
make benchmark-in      # comprar y mantener BTC
make analysis          # ¿de qué exit_tag sale el dinero?
```

Umbrales y plantilla de métricas: [VALIDACION.md](VALIDACION.md).

---

## 5. Arrancar el dry-run

```bash
make preflight    # 12 comprobaciones; tiene que salir sin FALLA
make up
```

`preflight.sh` verifica infraestructura (docker, disco, RAM, NTP), seguridad (permisos de `.env`, que no esté en git, API en loopback, password suficiente) y configuración (`dry_run: true`, capital coherente, sin claves en `config.json`, datos descargados, Telegram válido). Devuelve código 1 si hay fallos, así que sirve en un script.

### Tareas programadas

```bash
make cron-install
```

Instala cuatro tareas en tu crontab, dentro de un bloque delimitado que no toca el resto:

| Cuándo | Qué |
|---|---|
| 21:00 diario | Resumen a Telegram: operaciones, win rate, **valor esperado por operación**, drawdown |
| Cada 15 min | Vigilancia: contenedor caído, API sin responder, log congelado >2h, >20 ERROR, disco >85% |
| Domingos 04:00 | Respaldo de la base de datos, config, estrategias y resultados |
| Lunes 05:00 | Actualización incremental de datos (últimos 14 días) |

El watchdog silencia una alerta repetida durante 2 horas, así que un problema persistente no te llena el Telegram.

```bash
./scripts/daily_report.sh      # probar el resumen ahora
./scripts/watchdog.sh          # probar la vigilancia ahora
./scripts/cron-install.sh --show
```

### systemd (opcional)

`restart: unless-stopped` ya devuelve el bot tras un reinicio de la VM. La unidad en [`systemd/freqtrade-quant.service`](../systemd/freqtrade-quant.service) añade control con `systemctl`, estado y logs en journald:

```bash
sudo cp systemd/freqtrade-quant.service /etc/systemd/system/
sudo sed -i "s/__USER__/$USER/;s#__ROOT__#$PWD#" /etc/systemd/system/freqtrade-quant.service
sudo systemctl daemon-reload && sudo systemctl enable --now freqtrade-quant
```

Si la instalas, gestiona el bot **solo** con `systemctl`. Hacer `docker compose down` por detrás deja a systemd creyendo que el servicio sigue activo.

---

## 6. Prueba de resiliencia

Hazla una vez, antes de confiar en el sistema. Es una casilla del Bloque C de la checklist.

```bash
# Reinicio del contenedor
docker compose restart && sleep 30 && docker compose logs --tail 20

# Reinicio completo de la VM
sudo reboot
# volver a entrar y comprobar que subió solo:
docker compose ps
```

Lo que verificas: que el bot recupera su estado desde el sqlite y **no duplica** las operaciones abiertas.

---

## 7. Acceso a FreqUI

La API nunca se expone. Desde tu PC:

```bash
ssh -L 8080:127.0.0.1:8080 usuario@IP-DE-TU-VM
# dejar la terminal abierta y abrir http://localhost:8080
```

Usuario y contraseña están en `.env` (`FREQTRADE__API_SERVER__USERNAME` / `__PASSWORD`).

Comandos de Telegram, que casi siempre bastan: `/status`, `/profit`, `/daily 7`, `/performance`, `/balance`, `/stats`, `/stopentry`, `/forceexit <id>`, `/reload_config`.

---

## 8. Diagnóstico

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `permission denied` en `user_data` | El contenedor es uid 1000, tú no | `sudo chown -R 1000:1000 user_data` |
| `bad interpreter: ^M` | Finales de línea CRLF | `.gitattributes` lo evita; si pasó: `sed -i 's/\r$//' scripts/*.sh` |
| `missing separator` en make | Espacios en vez de tabs en el Makefile | No editar el Makefile en un editor que convierta tabs |
| El backtest devuelve lo mismo tras editar la estrategia | Caché de resultados | Siempre `--cache none` (ya está en el Makefile) |
| `No data found` | Falta el rango de calentamiento | `startup_candle_count = 900` consume ~37 días; descarga desde 2023-01-01 |
| Hyperopt muere sin mensaje | OOM | Añade swap, usa `-j 1`, baja `--epochs` |
| El bot no abre ninguna operación | El filtro de 4h no se cumple | Normal en mercado bajista. Verifica con `make analysis` |
| Telegram no llega | Token, chat_id o cron | `./scripts/preflight.sh`, luego `systemctl status cron` |
| `Invalid timestamp` de Binance | Reloj desfasado | `sudo timedatectl set-ntp true` |
| Disco lleno | Datos de 5m + logs | `du -sh user_data/*`; los logs de Docker ya rotan a 10 MB x 5 |
| El contenedor reinicia en bucle | Error en config o estrategia | `docker compose logs --tail 100` |

### Comandos de inspección

```bash
docker compose ps                  # estado
docker compose logs -f --tail 100  # logs en vivo
docker stats --no-stream           # CPU y RAM reales
du -sh user_data/*                 # qué ocupa el disco
sudo ss -tlnp | grep 8080          # debe decir 127.0.0.1, nunca 0.0.0.0
tail -f user_data/logs/watchdog.log
```

---

## 9. Mantenimiento

```bash
# Actualizar el código del proyecto
git pull && docker compose up -d

# Actualizar la imagen de Freqtrade
docker compose down && docker compose pull && docker compose up -d
# Tras actualizar la imagen, repetir make audit: una versión nueva puede
# cambiar el comportamiento de los indicadores.

# Respaldo manual
BACKUP_PASSPHRASE='algo-largo' ./scripts/backup.sh

# Reiniciar el dry-run desde cero
make clean-db && make up
```

### El respaldo solo sirve si sale de la VM

```bash
# desde tu PC
scp usuario@vm:~/freqtrade-backups/*.tar.gz ./backups/
```

Un respaldo en el mismo disco que pretende proteger no es un respaldo.

---

## 10. Antes de pasar a dinero real

No hay atajo: [CHECKLIST_REAL.md](CHECKLIST_REAL.md), los cinco bloques completos.

El resumen de lo que importa: **3-4 semanas de dry-run sin tocar nada**, el resultado comparado contra el backtest del mismo periodo, y la API key de Binance con trading spot únicamente, sin retiros, restringida a la IP estática de la VM.
