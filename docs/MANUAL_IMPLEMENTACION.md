# AutoEdit AI — Manual de Implementación

**Versión:** 1.1  
**Fecha:** 2026-05-11  
**Autor:** Josemiguel Escobedo Checa  
**Audiencia:** Ingenieros de deployment, DevOps y el propio usuario implementador.

---

## Tabla de Contenidos

1. [Requisitos del Sistema](#1-requisitos-del-sistema)
2. [Preparación del Entorno](#2-preparación-del-entorno)
3. [Instalación Paso a Paso (Local)](#3-instalación-paso-a-paso-local)
4. [Instalación Paso a Paso (Docker)](#4-instalación-paso-a-paso-docker)
5. [Configuración de Variables de Entorno](#5-configuración-de-variables-de-entorno)
6. [Descarga de Modelos de ML](#6-descarga-de-modelos-de-ml)
7. [Inicialización de Servicios](#7-inicialización-de-servicios)
8. [Configuración de Voz (TTS)](#8-configuración-de-voz-tts)
9. [Ingesta de Assets Iniciales](#9-ingesta-de-assets-iniciales)
10. [Verificación del Sistema](#10-verificación-del-sistema)
11. [Puesta en Marcha](#11-puesta-en-marcha)
12. [Troubleshooting](#12-troubleshooting)
13. [Mantenimiento y Actualización](#13-mantenimiento-y-actualización)
14. [Novedades v1.1](#14-novedades-v11)

---

## 1. Requisitos del Sistema

### 1.1 Hardware Recomendado

| Componente | Especificación Mínima | Recomendada |
|------------|----------------------|-------------|
| GPU | NVIDIA con NVENC | RTX 4070 Mobile (8 GB VRAM) o superior |
| CPU | 8 cores | Intel i9-13980HX (24 cores) o equivalente |
| RAM | 16 GB | 32 GB DDR5 |
| Almacenamiento | 256 GB SSD | 500 GB+ NVMe |
| Conexión | 50 Mbps | 100 Mbps+ estable |

### 1.2 Software Base (Local)

| Componente | Versión | Notas |
|------------|---------|-------|
| Windows | 11 22H2+ | Requerido para WSL2 y drivers NVIDIA |
| WSL2 | Default | Distribución Ubuntu 22.04 LTS |
| Ubuntu (WSL) | 22.04 LTS | Entorno de ejecución principal |
| Python | 3.12+ | Gestión via `uv` |
| Docker Desktop | 4.x+ | Backend WSL2 obligatorio |
| NVIDIA Driver | ≥ 555.x | Exponiendo CUDA a WSL2 |
| CUDA Toolkit | 12.x | Compatible con PyTorch cu128 |
| FFmpeg | 7.x+ | Compilado con soporte NVENC |

### 1.3 Software Base (Docker)

| Componente | Versión | Notas |
|------------|---------|-------|
| Docker Engine | 24.x+ | Con BuildKit habilitado |
| Docker Compose | 2.x+ | Soporte para perfiles (`--profile`) |
| NVIDIA Container Toolkit | 1.14+ | Para exponer GPU dentro de contenedores |
| NVIDIA Driver | ≥ 555.x | En el host |

### 1.4 Verificación Previa de FFmpeg

```bash
ffmpeg -hide_banner -encoders | grep nvenc
# Debe mostrar: h264_nvenc, hevc_nvenc, av1_nvenc
```

---

## 2. Preparación del Entorno

### 2.1 Instalar WSL2 y Ubuntu 22.04 (solo local)

```powershell
# En PowerShell como Administrador
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

Reiniciar y completar la configuración de usuario en Ubuntu.

### 2.2 Instalar NVIDIA Drivers en Windows

Descargar e instalar los drivers más recientes desde [nvidia.com/drivers](https://www.nvidia.com/drivers). WSL2 expondrá CUDA automáticamente si el driver es ≥ 555.x.

Verificar dentro de WSL:

```bash
nvidia-smi
# Debe mostrar la GPU y la versión del driver
```

### 2.3 Instalar Docker Desktop

1. Descargar desde [docker.com](https://www.docker.com/products/docker-desktop/).
2. En Settings → General, habilitar **"Use the WSL 2 based engine"**.
3. En Settings → Resources → WSL Integration, habilitar Ubuntu-22.04.

### 2.4 Instalar NVIDIA Container Toolkit (solo Docker)

Sigue la guía oficial: [docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

Verificar:

```bash
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

---

## 3. Instalación Paso a Paso (Local)

### 3.1 Clonar el Repositorio

```bash
git clone https://github.com/josecitho95-hue/EditorVideos.git
cd EditorVideos
```

### 3.2 Instalar `uv` (Gestor de Paquetes Python)

```bash
# En WSL2 / Ubuntu
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env  # o reiniciar la terminal
```

Verificar:

```bash
uv --version
```

### 3.3 Sincronizar Dependencias

```bash
uv sync --extra dev
```

Esto instalará todas las dependencias del proyecto incluyendo las de desarrollo (testing, linting) y **NiceGUI**.

### 3.4 Activar el Entorno (Opcional)

```bash
source .venv/bin/activate
# O usar prefijo uv run antes de cada comando
```

---

## 4. Instalación Paso a Paso (Docker)

### 4.1 Clonar y Configurar

```bash
git clone https://github.com/josecitho95-hue/EditorVideos.git
cd EditorVideos
cp .env.example .env
# Editar .env y establecer OPENROUTER_API_KEY
```

### 4.2 Construir la Imagen

```bash
docker compose build
```

La imagen se construye en 3 stages:
1. **base**: Sistema operativo + FFmpeg + uv + Python 3.12
2. **builder**: Descarga de dependencias Python (incluye PyTorch ~4 GB)
3. **runtime**: Imagen final ligera con el código fuente y el venv poblado

### 4.3 Inicializar Base de Datos (una vez)

```bash
docker compose --profile setup run --rm init-db
```

### 4.4 Descargar Modelos (una vez, ~10 GB)

```bash
docker compose --profile setup run --rm download-models
```

### 4.5 Levantar el Stack

```bash
docker compose up -d
```

Servicios disponibles:
- **GUI (NiceGUI)**: http://localhost:7880
- **Redis**: localhost:6379
- **Qdrant**: localhost:6333

---

## 5. Configuración de Variables de Entorno

### 5.1 Crear el archivo `.env`

Copiar el ejemplo proporcionado:

```bash
cp .env.example .env
```

Editar `.env` con los valores reales:

```bash
# === LLM (Obligatorio) ===
OPENROUTER_API_KEY=sk-or-v1-TU_API_KEY_AQUI

# === Storage ===
DATA_DIR=./data
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333

# === GPU ===
GPU_VRAM_BUDGET_MB=7000

# === Defaults LLM ===
DIRECTOR_MODEL=deepseek/deepseek-chat-v3
TRIAGE_MODEL=google/gemini-2.5-flash

# === Observabilidad (Opcional) ===
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# === FFmpeg ===
FFMPEG_BIN=ffmpeg
NVENC_PRESET=p4
NVENC_CQ=22

# === Twitch (Opcional, para poller automático) ===
TWITCH_CHANNEL_NAME=tu_canal
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=

# === Assets APIs (Opcional) ===
FREESOUND_API_KEY=
PIXABAY_API_KEY=
```

> **IMPORTANTE:** Nunca commitear el archivo `.env`. El `.gitignore` ya lo excluye.

### 5.2 Obtener API Key de OpenRouter

1. Registrar en [openrouter.ai](https://openrouter.ai/).
2. Generar una API key en el panel de control.
3. Copiarla en `OPENROUTER_API_KEY`.

---

## 6. Descarga de Modelos de ML

Los modelos se almacenan en `data/models/` (gitignored).

### 6.1 Local

```bash
uv run python infra/download_models.py
```

### 6.2 Docker

```bash
docker compose --profile setup run --rm download-models
```

### 6.3 Modelos Requeridos

| Modelo | Ubicación Esperada | Tamaño Aprox. |
|--------|-------------------|---------------|
| faster-whisper large-v3 | `data/models/faster-whisper-large-v3/` | ~3 GB |
| CLIP ViT-B/32 | `data/models/clip-vit-b-32/` | ~600 MB |
| F5-TTS | `data/models/f5-tts/` | ~800 MB |

Verificar que los directorios existen:

```bash
ls -lah data/models/
```

---

## 7. Inicialización de Servicios

### 7.1 Local — Redis y Qdrant

```bash
make up
# Equivalente a: docker compose up -d redis qdrant
```

### 7.2 Verificar Servicios

```bash
docker ps
# Debe mostrar redis:7-alpine y qdrant/qdrant:latest
```

### 7.3 Inicializar Qdrant (Crear Collections)

```bash
# Local
uv run python infra/qdrant_init.py

# Docker (ya incluido en el stack)
```

### 7.4 Inicializar Base de Datos SQLite

```bash
# Local
uv run autoedit db migrate

# Docker
docker compose --profile setup run --rm init-db
```

---

## 8. Configuración de Voz (TTS)

El sistema requiere un perfil de voz para generar narraciones clonadas.

### 8.1 Grabar Audio de Referencia

Requisitos del audio:
- **Duración mínima:** 15 segundos (recomendado: 30+ segundos).
- **Calidad:** Limpio, sin música de fondo ni SFX.
- **Formato:** Cualquier formato soportado por FFmpeg (WAV, MP3, MP4, etc.).

Guardar el archivo, por ejemplo: `~/mi_voz.wav`.

### 8.2 Registrar el Perfil de Voz

```bash
uv run autoedit voice register ~/mi_voz.wav me_v1 --name "Mi Voz"
```

El sistema:
1. Convierte el audio a 24 kHz mono WAV.
2. Transcribe automáticamente el contenido con Whisper (puedes proporcionar transcript manual con `--transcript`).
3. Almacena el perfil en `data/voices/me_v1/`.

### 8.3 Probar la Voz

```bash
uv run autoedit voice test "Esto es una prueba de narración con mi voz clonada" me_v1
```

Reproduce el resultado:

```bash
ffplay data/voices/me_v1/test_*.wav
```

---

## 9. Ingesta de Assets Iniciales

### 9.1 Ingestar Emotes (Sin API Key)

```bash
uv run autoedit assets ingest bttv 7tv ffz --limit 200
```

### 9.2 Ingestar SFX e Imágenes (Requiere API Keys)

```bash
# Si configuraste FREESOUND_API_KEY en .env
uv run autoedit assets ingest freesound --limit 100

# Si configuraste PIXABAY_API_KEY en .env
uv run autoedit assets ingest pixabay --limit 100
```

### 9.3 Verificar el Catálogo

```bash
uv run autoedit assets stats
```

---

## 10. Verificación del Sistema

### 10.1 Ejecutar Health Check Completo

```bash
uv run autoedit doctor
```

Salida esperada (ejemplo):

```
┌─────────────────────────────────────────────────────────────┐
│              AutoEdit AI — Health Check                     │
├─────────────────┬────────┬──────────────────────────────────┤
│ Check           │ Status │ Details                          │
├─────────────────┼────────┼──────────────────────────────────┤
│ Python 3.12+    │ OK     │ Python 3.12.4                    │
│ Redis           │ OK     │ Redis reachable at ...           │
│ Qdrant          │ OK     │ Qdrant at ... — 200              │
│ GPU (PyTorch)   │ OK     │ NVIDIA GeForce RTX 4070 ...      │
│ FFmpeg NVENC    │ OK     │ h264_nvenc, hevc_nvenc           │
│ Models          │ OK     │ Found 3/3 models                 │
│ Voice profile   │ OK     │ Voice profile: data/voices/...   │
│ Assets catalog  │ OK     │ Assets catalog: 150 visual, ...  │
└─────────────────┴────────┴──────────────────────────────────┘
All systems operational.
```

### 10.2 Probar Conexión con OpenRouter

```bash
uv run autoedit ping
```

---

## 11. Puesta en Marcha

### 11.1 Procesar un VOD de Twitch (Manual)

```bash
uv run autoedit job add "https://www.twitch.tv/videos/123456789" --clips 10 --lang es
```

El sistema ejecutará E0 → E4 automáticamente. Para continuar hasta clips finales:

```bash
# Re-dirección editorial (E5-E8)
uv run autoedit job direct <JOB_ID>

# Renderizado final (E9)
uv run autoedit render edit --job-id <JOB_ID>
```

### 11.2 Procesar un Video Local

```bash
uv run autoedit job local ~/Videos/mi_video.mp4 --clips 5 --until e8
```

### 11.3 Lanzar el Editor Visual (NiceGUI)

```bash
uv run autoedit gui
```

Abre automáticamente [http://localhost:7880](http://localhost:7880).

Para cambiar de puerto:

```bash
uv run autoedit gui --port 7881
```

Para no abrir el navegador automáticamente:

```bash
uv run autoedit gui --no-browser
```

### 11.4 Lanzar el Dashboard (Gradio) — alternativa ligera

```bash
uv run autoedit dashboard
```

Abre automáticamente [http://localhost:7860](http://localhost:7860).

### 11.5 Worker en Background (Opcional)

```bash
make worker
# o
uv run autoedit worker run
```

---

## 12. Troubleshooting

### 12.1 CUDA no disponible en WSL2

**Síntoma:** `torch.cuda.is_available()` devuelve `False`.

**Soluciones:**
1. Verificar driver NVIDIA en Windows con `nvidia-smi`.
2. Reinstalar PyTorch con índice CUDA correcto:
   ```bash
   uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
   ```
3. Asegurar que WSL2 tiene acceso a la GPU:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
   ```

### 12.2 Out of Memory (OOM) durante pipeline

**Síntoma:** Error `CUDA out of memory` en E2, E6 o E8.

**Soluciones:**
1. Cerrar aplicaciones que usen GPU (navegadores, juegos).
2. Reducir `GPU_VRAM_BUDGET_MB` en `.env` (ej. a 6000).
3. Verificar que solo un worker corre a la vez.
4. Reiniciar WSL2: `wsl --shutdown` y volver a iniciar.

### 12.3 Redis o Qdrant no responden

**Síntoma:** `doctor` marca FAIL en Redis/Qdrant.

**Soluciones:**
```bash
make down
make up
docker logs redis
docker logs qdrant
```

### 12.4 yt-dlp falla en descarga

**Síntoma:** Error 403 o VOD no encontrado.

**Soluciones:**
1. Actualizar yt-dlp:
   ```bash
   uv pip install -U yt-dlp
   ```
2. Verificar que el VOD es público.
3. Si Twitch requiere login, considerar cookies (no implementado en sprint actual).

### 12.5 F5-TTS genera audio distorsionado

**Síntoma:** La narración suena robótica o con ruido.

**Soluciones:**
1. Verificar que el audio de referencia tiene ≥ 15s y está limpio.
2. Re-registrar el perfil con mejor calidad de audio.
3. Asegurar que el texto de narración no excede 300 caracteres.

### 12.6 FFmpeg no encuentra NVENC

**Síntoma:** `doctor` muestra "No NVENC encoders found".

**Soluciones:**
1. Instalar FFmpeg desde [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (builds full).
2. Verificar que el binario está en PATH:
   ```bash
   which ffmpeg
   ffmpeg -hide_banner -encoders | grep nvenc
   ```

### 12.7 NiceGUI no carga el timeline canvas

**Síntoma:** El editor de timeline aparece en blanco.

**Soluciones:**
1. Verificar que no hay bloqueadores de JavaScript en el navegador.
2. Revisar consola del navegador (F12) por errores de `timeline.js`.
3. Recargar la página con Ctrl+F5 (hard refresh).

### 12.8 Docker — GPU no disponible en contenedor

**Síntoma:** El worker Docker no detecta CUDA.

**Soluciones:**
1. Verificar que NVIDIA Container Toolkit está instalado en el host.
2. Verificar que el daemon de Docker reconoce el runtime nvidia:
   ```bash
   docker info | grep -i nvidia
   ```
3. Reiniciar Docker Desktop después de instalar el toolkit.

---

## 13. Mantenimiento y Actualización

### 13.1 Actualizar Dependencias

```bash
uv sync --extra dev
```

### 13.2 Actualizar Modelos

```bash
rm -rf data/models/*
uv run python infra/download_models.py
```

### 13.3 Backup de la Base de Datos

```bash
uv run autoedit db backup
# Crea: data/autoedit.db.backup.YYYY-MM-DD_HHMMSS
```

### 13.4 Limpieza de Archivos Temporales

```bash
# Limpiar caché TTS antiguo (> 90 días)
find data/cache/tts -type f -mtime +90 -delete

# Limpiar tmp/
rm -rf tmp/*
```

### 13.5 Actualizar yt-dlp

```bash
uv pip install -U yt-dlp
```

### 13.6 Actualizar Imagen Docker

```bash
docker compose build --no-cache
docker compose up -d
```

---

## 14. Novedades v1.1

### 14.1 Instalación Docker

A partir de la v1.1, el proyecto incluye soporte completo para Docker:

- **Dockerfile multi-stage** optimizado para CUDA 12.8 + cuDNN 9.
- **Docker Compose** con servicios: Redis, Qdrant, GUI (NiceGUI) y Worker.
- **Perfiles de setup** (`--profile setup`) para inicialización y descarga de modelos.
- El stack Docker es la forma recomendada de deployment para producción o para evitar configurar WSL2 manualmente.

### 14.2 Nueva Interfaz — Editor NiceGUI

La v1.1 introduce un editor visual completo que coexiste con el Dashboard Gradio:

- **NiceGUI** requiere `nicegui>=1.4` (ya incluido en `pyproject.toml`).
- Se lanza con `autoedit gui` en el puerto 7880.
- En Docker, el servicio `gui` expone automáticamente el puerto 7880.

### 14.3 Layout Split-Screen

Nuevo parámetro `--layout` en el comando `render`:

- **`crop`** (default): recorte tradicional.
- **`split`**: pantalla dividida para formato vertical. Requiere MediaPipe para detección facial.

### 14.4 Deduplicación

Nueva etapa automática post-E7 que reduce clips duplicados. No requiere configuración manual; el umbral IoU se puede ajustar en código si es necesario.

---

*Fin del Manual de Implementación v1.1.*
