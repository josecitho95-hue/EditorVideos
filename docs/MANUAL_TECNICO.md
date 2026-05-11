# AutoEdit AI — Manual Técnico

**Versión:** 1.1  
**Fecha:** 2026-05-11  
**Autor:** Josemiguel Escobedo Checa  
**Audiencia:** Equipos de desarrollo, arquitectos de software, DevOps y mantenedores del sistema.

---

## Tabla de Contenidos

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Arquitectura de Alto Nivel](#2-arquitectura-de-alto-nivel)
3. [Stack Tecnológico](#3-stack-tecnológico)
4. [Modelo de Datos](#4-modelo-de-datos)
5. [Pipeline End-to-End](#5-pipeline-end-to-end)
6. [Especificación por Componente](#6-especificación-por-componente)
7. [Gestión de Recursos GPU](#7-gestión-de-recursos-gpu)
8. [Integración con LLMs (OpenRouter)](#8-integración-con-llms-openrouter)
9. [Renderizado con FFmpeg + NVENC](#9-renderizado-con-ffmpeg--nvenc)
10. [Observabilidad y Trazabilidad](#10-observabilidad-y-trazabilidad)
11. [Testing y Calidad](#11-testing-y-calidad)
12. [Seguridad y Configuración](#12-seguridad-y-configuración)
13. [Novedades v1.1](#13-novedades-v11)

---

## 1. Resumen Ejecutivo

**AutoEdit AI** es una plataforma local-first que transforma VODs (Videos on Demand) de Twitch de larga duración (1-8 horas) en clips editados al estilo creator-comedy. El sistema emplea una cascada de señales multiformato (audio, chat, transcripción, escenas) para identificar momentos destacados, los cuales son posteriormente enriquecidos por agentes de LLM con memes, SFX, zooms dinámicos, subtítulos estilo karaoke y narración con voz clonada.

### Formatos de Salida

| Formato | Resolución | Aspecto | Layout | Destino |
|---------|------------|---------|--------|---------|
| YouTube | 1920×1080 | 16:9 | crop (default) | Principal |
| TikTok / Reels / Shorts | 1080×1920 | 9:16 | crop o split | Derivados |
| Square | 1080×1080 | 1:1 | crop | Redes sociales |

El **layout split-screen** divide la pantalla vertical en gameplay arriba (60 %) y primer plano facial abajo (40 %), ambos tomados del mismo video fuente. Esto maximiza el engagement en formatos verticales sin requerir cámara secundaria.

### Métricas de Diseño

| Métrica | Objetivo |
|---------|----------|
| Tiempo de procesamiento | ≤ 45 min por hora de VOD |
| Volumen esperado | 1 video por día |
| Costo LLM por video | < $0.20 USD (default) / < $2.00 (calidad) |
| Infraestructura mensual | $0 (local + free tiers) |
| Clips objetivo por VOD | 5-15 candidatos finales |
| Deduplicación post-E7 | IoU ≥ 0.40 suprime clips duplicados |

---

## 2. Arquitectura de Alto Nivel

### 2.1 Diagrama de Componentes

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              USUARIO                                          │
│   CLI (Typer)  ◄──►  Dashboard (Gradio)  ◄──►  Editor (NiceGUI)              │
└────────────────┬─────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        APPLICATION LAYER (Python 3.12)                        │
│                                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────────────────┐  │
│  │  Pipeline    │  │  GPU         │  │  Cost & Trace Recorder              │  │
│  │  Orchestrator│◄─┤  Scheduler   │  │  (Langfuse SDK)                     │  │
│  │  (Pydantic   │  │  (1 etapa    │  └─────────────────────────────────────┘  │
│  │   AI graph)  │  │   GPU/vez)   │                                         │  │
│  └──────┬───────┘  └──────────────┘                                         │  │
│         │                                                                     │
│         ▼                                                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐   │
│  │  Domain Services                                                        │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐    │   │
│  │  │Ingest  │ │Analyze │ │Score   │ │Triage  │ │Director│ │Dedup   │    │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘    │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐               │   │
│  │  │Retrieve│ │TTS     │ │Render  │ │Split   │ │Publish │               │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘               │   │
│  └────────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└──┬────────────┬─────────────┬──────────────┬─────────────┬────────────┬──────┘
   │            │             │              │             │            │
   ▼            ▼             ▼              ▼             ▼            ▼
┌────────┐ ┌─────────┐  ┌─────────┐  ┌────────────┐  ┌──────────┐  ┌────────┐
│SQLite  │ │ Qdrant  │  │ Redis   │  │ Filesystem │  │OpenRouter│  │Docker  │
│(estado │ │(vector  │  │(arq job │  │(VODs,clips,│  │(LLMs HTTP│  │(runtime│
│ ops)   │ │  search)│  │ queue)  │  │ assets,    │  │ remoto)  │  │ stack) │
│        │ │ Docker  │  │ Docker  │  │ models)    │  │          │  │        │
└────────┘ └─────────┘  └─────────┘  └────────────┘  └──────────┘  └────────┘
```

### 2.2 Capas de la Aplicación

| Capa | Responsabilidad | Tecnología |
|------|-----------------|------------|
| **Presentación** | Interacción usuario-sistema | Typer (CLI), Gradio (Dashboard), NiceGUI (Editor) |
| **Orquestación** | Coordinación del pipeline E0-E10 | Pydantic AI, asyncio |
| **Dominio** | Entidades de negocio tipadas | Pydantic v2 |
| **Servicios** | Lógica de análisis, scoring, editorial, deduplicación | Python puro |
| **Infraestructura** | Persistencia, colas, vectores, render, contenedores | SQLModel, Redis, Qdrant, FFmpeg, Docker |

---

## 3. Stack Tecnológico

| Capa | Tecnología | Versión | Propósito |
|------|------------|---------|-----------|
| Lenguaje | Python | 3.12+ | Runtime principal |
| Gestor de paquetes | uv | latest | Resolución de dependencias y entornos |
| Validación | Pydantic | 2.x | Schemas de dominio y configuración |
| Configuración | pydantic-settings | 2.x+ | Carga desde `.env` |
| ORM | SQLModel | latest | Modelado sobre SQLite |
| Base de datos | SQLite | 3.45+ | Estado operacional, WAL mode |
| Vector DB | Qdrant | 1.11+ | Búsqueda semántica de assets (Docker) |
| Cola de trabajos | arq | 0.26+ | Worker async con backend Redis |
| Cache/Broker | Redis | 7.x | Backend de arq y caché (Docker) |
| Cliente HTTP | httpx | 0.27+ | Async, timeouts explícitos |
| Gateway LLM | OpenRouter | — | API única para múltiples LLM |
| SDK LLM | openai | 1.x | Cliente compatible OpenRouter |
| Agente editorial | Pydantic AI | 0.0.x | Tipado estructurado de respuestas LLM |
| CLI | Typer | 0.12+ | Interfaz de línea de comandos |
| Dashboard | Gradio | 6.10+ | Interfaz web de revisión rápida |
| Editor visual | NiceGUI | 1.4+ | Timeline interactivo con canvas JS |
| Logging | loguru | 0.7+ | JSON sink + consola |
| Tracing | langfuse | 2.x | Observabilidad de llamadas LLM |
| Testing | pytest | 8.x+ | Unit, integración y E2E |
| Lint/Format | ruff | latest | Reemplazo de black+isort+flake8 |
| Type check | mypy | 1.x | Modo estricto |
| Contenedores | Docker + Compose | — | Runtime reproducible con CUDA |
| Video/Audio | FFmpeg | 7.x+ | Render con NVENC |
| Descarga VOD | yt-dlp | latest | Descarga de streams Twitch |
| Chat Twitch | chat-downloader | latest | Extracción de historial de chat |
| Análisis audio | librosa, pyloudnorm | 0.10+ | RMS, loudness, pitch, risa |
| Detección escenas | PySceneDetect | 0.6+ | Segmentación por contenido |
| Tracking facial | mediapipe | 0.10+ | Detección de rostro para reframe y split |
| Transcripción | faster-whisper | 1.0+ | large-v3, int8 |
| Embeddings imagen | open_clip_torch | 3.3+ | ViT-B/32 |
| TTS | F5-TTS | 1.1.20+ | Voice cloning |
| ML runtime | torch | 2.4+ | CUDA 12.x |

---

## 4. Modelo de Datos

### 4.1 SQLite — Tablas Principales

| Tabla | Propósito |
|-------|-----------|
| `jobs` | Trabajos de procesamiento encolados o ejecutados |
| `vods` | Metadatos de videos originales descargados |
| `run_steps` | Traza de ejecución por etapa (idempotencia) |
| `transcript_segments` | Segmentos de transcripción Whisper |
| `transcript_words` | Palabras con timestamps (para subtítulos karaoke) |
| `chat_messages` | Mensajes de chat de Twitch |
| `windows` | Candidatos temporales generados por scoring |
| `highlights` | Momentos validados post-triage con intención |
| `edit_decisions` | Planes editoriales JSON tipados por highlight |
| `clips` | Archivos MP4 finales renderizados |
| `assets` | Catálogo de memes, imágenes y SFX |
| `asset_usages` | Traza de uso de assets en clips |
| `narrations` | Caché global de audios TTS generados |
| `cost_entries` | Registro granular de costos por llamada LLM |

### 4.2 Qdrant — Collections

| Collection | Dimensión | Distancia | Payload |
|------------|-----------|-----------|---------|
| `assets_visual` | 512 (CLIP ViT-B/32) | Coseno | `asset_id`, `tags`, `intent_affinity`, `kind` |
| `assets_audio` | 512 (LAION-CLAP) | Coseno | `asset_id`, `tags`, `intent_affinity`, `duration_sec` |
| `transcript_chunks` | 384 (BGE-small) | Coseno | `vod_id`, `start_sec`, `end_sec`, `text` |

### 4.3 Filesystem Layout

```
data/
├── autoedit.db              # SQLite operacional
├── vods/{vod_id}/
│   ├── source.mp4           # Original (borrable post-job)
│   ├── audio.wav            # 16 kHz mono PCM
│   ├── chat.jsonl           # Mensajes en NDJSON
│   ├── transcript.json      # Output completo WhisperX
│   ├── scenes.json          # Cortes de PySceneDetect
│   ├── signals.parquet      # Señales multiformato por segundo
│   ├── tts/                 # Narraciones específicas del VOD
│   └── clips/               # MP4 finales + metadatos
├── assets/
│   ├── visual/              # Imágenes y memes
│   ├── audio/               # SFX
│   └── emotes/              # Emotes de BTTV/7TV/FFZ
├── voices/{voice_id}/
│   └── ref.wav              # Audio de referencia 24 kHz mono
├── cache/
│   ├── tts/                 # Narraciones reutilizables (TTL 90 días)
│   ├── triage/              # Respuestas cacheadas de Gemini Flash
│   └── embeddings/          # Vectores precalculados
└── models/                  # Modelos descargados (gitignored)
    ├── faster-whisper-large-v3/
    ├── clip-vit-b-32/
    └── f5-tts/
```

---

## 5. Pipeline End-to-End

El pipeline se ejecuta en etapas secuenciales, con cacheo de artefactos y scheduling GPU para evitar colisiones de VRAM.

### 5.1 Etapas del Pipeline

| Etapa | Nombre | Recurso Principal | Descripción |
|-------|--------|-------------------|-------------|
| **E0** | Ingest | I/O (red) | Descarga VOD con yt-dlp y chat con chat-downloader |
| **E1** | Extract | CPU | Extracción de audio WAV y detección de escenas |
| **E2** | Transcribe | GPU (~3 GB) | Transcripción con faster-whisper + alineación word-level |
| **E3** | Analyze | CPU | Señales de audio (librosa, risa), chat (densidad), transcripción (keywords) |
| **E4** | Score | CPU | Fusión de señales y detección de ventanas top-N |
| **E5** | Triage | LLM (HTTP) | Clasificación de intención por candidato (Gemini Flash) |
| **E6** | Retrieve | GPU (~2 GB) | Búsqueda semántica de memes (CLIP) y SFX (CLAP) en Qdrant |
| **E7** | Direct | LLM (HTTP) | Agente editorial emite `EditDecision` tipado (DeepSeek V3) |
| **E7.5** | Dedup | CPU | IoU NMS sobre rangos renderizados; suprime duplicados (IoU ≥ 0.40) |
| **E8** | TTS | GPU (~4 GB) | Generación de narraciones con voz clonada (F5-TTS) |
| **E9** | Render | GPU (NVENC) | Composición final con FFmpeg: trim, overlays, subs, zooms, split |
| **E10** | Finalize | CPU/IO | Escritura de metadatos, limpieza opcional |

### 5.2 Secuencia GPU Crítica

```
E2 (Whisper) → liberar VRAM → E6 (CLIP+CLAP) → liberar VRAM → E8 (F5-TTS) → liberar VRAM → E9 (NVENC)
```

Las etapas E5 y E7 son llamadas HTTP a OpenRouter y no utilizan GPU local.

### 5.3 Idempotencia y Cacheo

Cada etapa:
1. Calcula un hash SHA-256 de sus inputs serializados.
2. Verifica si el artefacto de salida ya existe y el hash coincide.
3. Si coincide → marca el `run_step` como `cached` y omite ejecución.
4. Si no coincide → ejecuta, persiste artefactos y registra el paso en SQLite.

Esto permite reanudar jobs interrumpidos o re-ejecutar parcialmente desde cualquier etapa.

---

## 6. Especificación por Componente

### 6.1 Domain (`src/autoedit/domain/`)

Contiene las entidades centrales del negocio como Pydantic models inmutables:

- **`Job` / `JobConfig`**: Configuración y estado del trabajo.
- **`WindowCandidate`**: Ventana temporal candidata con puntuación de fusión.
- **`Highlight`**: Candidato validado post-triage con intención clasificada.
- **`EditDecision`**: Plan editorial completo (trim, zooms, memes, SFX, narración, estilo de subtítulos).
- **`Clip`**: Metadatos del archivo renderizado final.
- **`Asset`**: Elemento del catálogo (visual o audio).

### 6.2 Pipeline (`src/autoedit/pipeline/`)

- **`orchestrator.py`**: Enlace secuencial de nodos E0-E8 con manejo de excepciones y actualización de estado en DB.
- **`state.py`**: Objeto compartido `PipelineState` que transporta vod_id, rutas, config y resultados parciales entre nodos.
- **`nodes/e{0..8}_*.py`**: Implementación individual de cada etapa. Cada nodo declara sus requisitos de GPU y sus artefactos de entrada/salida.

### 6.3 Ingest (`src/autoedit/ingest/`)

- **`twitch_vod.py`**: Wrapper sobre `yt-dlp` para descarga progresiva de VODs. Extrae metadatos (id, duración, título, streamer).
- **`twitch_chat.py`**: Wrapper sobre `chat-downloader` para obtener el historial de mensajes en formato NDJSON.

### 6.4 Analysis (`src/autoedit/analysis/`)

- **`audio.py`**: Cálculo de RMS, loudness LUFS, pitch y detección de risa con librosa/pyloudnorm.
- **`chat.py`**: Densidad de mensajes, usuarios únicos, puntuación de keywords (emotes), sentimiento.
- **`scenes.py`**: Facade sobre PySceneDetect (`ContentDetector`) para obtener cortes de escena.
- **`transcribe.py` / `transcribe_local.py` / `transcribe_remote.py`**: Capa de transcripción con faster-whisper (local) o OpenRouter (remoto).
- **`transcript_signals.py`**: Detección de picos de keywords y sentimiento en la transcripción.
- **`vision.py`**: Análisis visual con MediaPipe para detección facial (usado por reframe y split-screen).

### 6.5 Scoring (`src/autoedit/scoring/`)

- **`fusion.py`**: Normaliza señales de audio, chat, transcripción y escenas a [0,1], aplica pesos configurables y genera una serie de scores por segundo.
- **`windowing.py`**: Detección de picos, aplicación de NMS (Non-Maximum Suppression) temporal y extracción de ventanas top-N respetando duración mínima/máxima.
- **`dedup.py`**: Deduplicación post-E7 basada en IoU (Intersection-over-Union) sobre los rangos de tiempo absolutos renderizados. Umbral por defecto: 0.40. Ordena por confianza de triage descendente y aplica NMS para evitar clips duplicados.

### 6.6 Editorial (`src/autoedit/editorial/`)

- **`triage.py`**: Invoca Gemini Flash vía OpenRouter con visión (frames de la ventana) para clasificar intención y descartar falsos positivos.
- **`director.py`**: Agente Pydantic AI que invoca DeepSeek V3. Emite `EditDecision` estrictamente validado contra JSON Schema.
- **`prompts/`**: Templates de prompts versionados en Markdown para triage, director y narración.

### 6.7 Assets (`src/autoedit/assets/`)

- **`ingest/`**: Scripts de ingesta de emotes (BTTV, 7TV, FFZ), SFX (Freesound) e imágenes (Pixabay).
- **`embeddings.py`**: Generación de vectores con CLIP (visual) y CLAP (audio).
- **`retrieval.py`**: Búsqueda híbrida en Qdrant: similitud vectorial + filtrado por `intent_affinity`.
- **`deduplication.py`**: Evita reusar el mismo asset en clips consecutivos dentro de una ventana temporal.

### 6.8 TTS (`src/autoedit/tts/`)

- **`f5_engine.py`**: Wrapper sobre F5-TTS para clonación de voz a partir de un archivo `ref.wav`.
- **`narration_cache.py`**: Caché persistente en SQLite + filesystem. La clave es `sha256(text + voice_id)`. TTL 90 días, LRU si excede 5 GB.

### 6.9 Render (`src/autoedit/render/`)

- **`ffmpeg_runner.py`**: Invoca FFmpeg como subproceso, parsea progreso y maneja errores.
- **`compositor.py`**: Traduce `EditDecision` en un comando FFmpeg completo con `filter_complex`.
- **`reframe.py`**: Adaptación de aspecto 16:9 → 9:16 / 1:1 con seguimiento facial (MediaPipe) + suavizado Kalman. Soporta layouts:
  - **`crop`** (default): recorte centrado o con seguimiento facial.
  - **`split`**: pantalla dividida — gameplay arriba (60 %) + primer plano facial abajo (40 %).
- **`subtitles.py`**: Genera subtítulos ASS con efecto karaoke word-level a partir de la alineación WhisperX.
- **`filters/`**: Helpers de filter_complex para overlays, zooms y mezcla de audio.

### 6.10 CLI (`src/autoedit/cli/`)

- **`main.py`**: Punto de entrada Typer. Agrupa comandos por dominio. Incluye `dashboard` (Gradio) y `gui` (NiceGUI).
- **`commands/job.py`**: `add`, `local`, `list`, `show`, `direct`.
- **`commands/assets.py`**: `ingest`, `list`, `stats`, `search`.
- **`commands/voice.py`**: `register`, `list`, `delete`, `test`.
- **`commands/doctor.py`**: Health check de todo el stack.
- **`commands/db.py`**: `migrate`, `reset`, `backup`.
- **`commands/worker.py`**: Gestión del worker arq.
- **`commands/render.py`**: Render manual de highlights. Soporta `--format` (`youtube`, `tiktok`, `shorts`, `square`) y `--layout` (`crop`, `split`).

### 6.11 Dashboard (`src/autoedit/dashboard/`)

- **`app.py`**: Aplicación Gradio con 3 tabs:
  - **Jobs**: Listado de trabajos con estado y etapa actual.
  - **Clips Viewer**: Previsualización de clips, rating 1-5 estrellas, notas, re-render.
  - **Re-direct**: Re-ejecución de E6-E8 sin reprocesar E1-E5.

### 6.12 Editor Visual — NiceGUI (`src/autoedit/gui/`)

Nueva interfaz web full-featured reemplazando/proporcionando una alternativa más potente al Dashboard Gradio.

- **`app.py`**: Entry point de NiceGUI. Registra rutas FastAPI para comunicación JS↔Python (`/api/gui/timeline/update`, `/api/gui/timeline/select`). Sirve archivos estáticos.
- **`data.py`**: Capa de acceso a datos para la UI — wrappers sobre repositories.
- **`pages/jobs.py`**: Grid de tarjetas de jobs con badges de estado, iconos por etapa, y navegación a timeline/clips.
- **`pages/timeline.py`**: Editor de timeline interactivo con:
  - **Sidebar**: Lista de highlights con intención, confianza y ventana temporal.
  - **Canvas JS**: Timeline basado en canvas con tracks de Trim, Zooms, Memes, SFX y Narración.
  - **Panel de propiedades**: Formularios dinámicos según el elemento seleccionado (intensidad de zoom, texto de narración, etc.).
  - **Botones de acción**: Guardar, Re-render, TikTok, Split.
  - **Comunicación bidireccional**: JS envía actualizaciones vía POST a FastAPI; Python inyecta datos con `ui.run_javascript`.
- **`pages/clips.py`**: Galería de clips renderizados con estadísticas (total, en disco, valorados), ratings con estrellas, y acciones (abrir carpeta, copiar ruta).
- **`static/timeline.js`**: Motor de timeline en canvas puro:
  - Tracks visuales con colores distintivos.
  - Drag & drop de handles y bloques.
  - Zoom temporal (pixels per second).
  - Selección y envío de estado a Python.

### 6.13 Storage (`src/autoedit/storage/`)

- **`db.py`**: Engine SQLModel, sesiones y migraciones automáticas.
- **`repositories/`**: Patrón Repository para cada agregado (jobs, vods, highlights, clips, assets, etc.).

### 6.14 LLM (`src/autoedit/llm/`)

- **`openrouter.py`**: Cliente HTTP único async con base_url apuntando a OpenRouter.
- **`pricing.py`**: Tabla de precios por modelo para estimación de costos.
- **`retry.py`**: Backoff exponencial con circuit breaker (umbrales configurables).

---

## 7. Gestión de Recursos GPU

### 7.1 Restricción Principal

Con 8 GB VRAM (RTX 4070 Mobile) no es posible cargar Whisper + CLIP + F5-TTS simultáneamente.

| Modelo | VRAM Aproximada |
|--------|-----------------|
| faster-whisper large-v3 (int8) | ~3.0 GB |
| WhisperX align (wav2vec2) | ~1.5 GB |
| open_clip ViT-B/32 | ~0.6 GB |
| LAION-CLAP | ~1.0 GB |
| F5-TTS | ~4.0 GB |
| FFmpeg NVENC | < 0.5 GB (encoder dedicado) |

### 7.2 Política de Scheduling

El sistema utiliza un scheduler GPU que implementa un mutex async global:

1. Cada nodo declara los modelos que necesita.
2. El scheduler verifica si caben en el budget de VRAM configurado (`GPU_VRAM_BUDGET_MB`).
3. Si no caben, evicta modelos LRU previos mediante `torch.cuda.empty_cache()` y `del model`.
4. Adquiere lock de compute (excluyente).
5. Ejecuta el callback del nodo.
6. Libera el lock.

NVENC opera fuera del compute lock porque utiliza un bloque de hardware separado del compute CUDA.

---

## 8. Integración con LLMs (OpenRouter)

### 8.1 Arquitectura de Gateway

Todas las llamadas a LLM se centralizan en un único cliente HTTP apuntado a `https://openrouter.ai/api/v1`. Esto permite:

- **Una sola API key** para múltiples modelos.
- **Modelos por defecto**:
  - Director (editorial pesada): `deepseek/deepseek-chat-v3`
  - Triage (filtrado barato): `google/gemini-2.5-flash`
- **Fallback automático**: El circuit breaker detecta fallos consecutivos y puede degradar a modelos alternativos.

### 8.2 Control de Costos

- Cada llamada registrada en `cost_entries` con tokens in/out y costo USD estimado.
- Dashboard de costos acumulados por job y por etapa.
- Target: < $0.20 por video en modo default.

### 8.3 Prompt Engineering

Los prompts se mantienen en archivos Markdown versionados (`src/autoedit/editorial/prompts/`). El Director recibe:

- Transcripción del highlight.
- Frames representativos (base64 para modelos con visión).
- Catálogo de memes/SFX disponibles (top-K recuperados).
- JSON Schema de `EditDecision` para forzar respuesta estructurada.

---

## 9. Renderizado con FFmpeg + NVENC

### 9.1 Pipeline de Render

El renderizado es un único paso de FFmpeg optimizado para minimizar pérdida de calidad:

1. **Trim**: `-ss start -to end` sobre el source MP4.
2. **Reframe / Split**:
   - **`crop`**: Recorte centrado o con seguimiento facial.
   - **`split`**: Composición split-screen para 9:16 — gameplay arriba (60 %) + cara abajo (40 %).
3. **Overlays**: Memes e imágenes con `overlay` filter y `enable='between(t,...)'`.
4. **Zooms**: `zoompan` para punch-ins y seguimiento facial.
5. **Subtítulos**: Burn-in ASS con estilo karaoke (`\k` tags).
6. **Audio mix**: Mezcla de audio original (con ducking durante narración), SFX y narración TTS.
7. **Encode**: NVENC H.264/HEVC/AV1 según configuración.

### 9.2 Layout Split-Screen

El layout split-screen está diseñado para maximizar el engagement en TikTok/Reels/Shorts sin requerir cámara secundaria:

```
┌─────────────────┐  ▲ top_h  (60 % de 1080×1920 = 1152 px)
│   GAMEPLAY      │  │  Recorte AR-match del source, centrado
│   (top 60 %)    │  │
└─────────────────┘  ▼
┌─────────────────┐  ▲ bot_h  (40 % de 1080×1920 = 768 px)
│  FACE CLOSE-UP  │  │  40 % de la altura del source alrededor de la cara detectada
│  (bottom 40 %)  │  │
└─────────────────┘  ▼
```

La posición facial se obtiene mediante MediaPipe Face Detection, agregada sobre múltiples frames del clip, y suavizada. Si no se detecta rostro, cae al centro vertical del frame.

### 9.3 Optimizaciones

- **NVENC preset p4**: Balance calidad/velocidad para RTX 4070 Mobile.
- **CQ 22**: Calidad visual objetivo.
- **`-movflags +faststart`**: Moov atom al inicio para streaming.
- Audio AAC 128-192 kbps estéreo.

---

## 10. Observabilidad y Trazabilidad

### 10.1 Logging

- **loguru** con sinks JSON rotativos y salida de consola colorizada.
- Cada job tiene un contexto de trace (`job_id`) inyectado en todos los logs.

### 10.2 Tracing LLM

- **Langfuse** SDK integrado para tracing de spans de triage y director.
- Permite visualizar latencia, tokens y costos por llamada.

### 10.3 Métricas

- Contadores in-process de jobs procesados, clips generados, fallos por etapa.
- Costo acumulado por job consultable vía CLI y dashboard.

---

## 11. Testing y Calidad

### 11.1 Pirámide de Tests

| Nivel | Herramienta | Cobertura Objetivo |
|-------|-------------|-------------------|
| Unit | pytest | ≥ 85% lógica de dominio |
| Integración | pytest + SQLite in-memory | Pipeline E0-E4 sin GPU |
| E2E | pytest + mocks LLM | Pipeline completo con fixture 30s |

### 11.2 Calidad de Código

- **ruff**: Lint y formato automático (reemplaza black, isort, flake8).
- **mypy**: Modo estricto sobre todo `src/`.
- **pytest-cov**: Reporte HTML en `htmlcov/` con umbral mínimo del 20% (creciente por sprint).

### 11.3 CI/CD

- Workflow GitHub Actions en `.github/workflows/ci.yml` ejecuta lint, typecheck y tests en cada push.

---

## 12. Seguridad y Configuración

### 12.1 Secrets y Variables de Entorno

Toda la configuración sensible se carga desde `.env` (nunca commiteado):

| Variable | Sensibilidad | Descripción |
|----------|--------------|-------------|
| `OPENROUTER_API_KEY` | **Alta** | Acceso a todos los LLM |
| `FREESOUND_API_KEY` | Media | Ingesta de SFX |
| `PIXABAY_API_KEY` | Media | Ingesta de imágenes |
| `TWITCH_CLIENT_ID` / `SECRET` | Media | Poller automático de VODs |
| `LANGFUSE_PUBLIC_KEY` / `SECRET_KEY` | Media | Observabilidad LLM |

### 12.2 Políticas de .gitignore

- `.env`, `.env.*` excluidos.
- `data/`, `models/`, `tmp/` excluidos (contenido pesado y generado).
- `*.db`, `*.parquet`, `*.log` excluidos.
- Cachés de herramientas (`.mypy_cache`, `.pytest_cache`, `.ruff_cache`) excluidos.

### 12.3 Acceso Local

- Mono-tenant: sin autenticación ni autorización.
- Dashboard Gradio expuesto solo en `localhost` (`share=False`).
- Editor NiceGUI expuesto solo en `localhost` (`share=False`).
- No hay endpoints públicos; todo el procesamiento es local-first.

---

## 13. Novedades v1.1

### 13.1 Editor Visual NiceGUI

Nueva interfaz web de alto rendimiento basada en NiceGUI + FastAPI + Canvas JS:

- **Timeline interactivo** con drag & drop de efectos, handles de trim, y selección visual.
- **Panel de propiedades dinámico** que cambia según el tipo de efecto seleccionado.
- **Comunicación bidireccional** JS↔Python vía endpoints FastAPI.
- **Persistencia** de cambios en SQLite con un solo clic en "Guardar".
- **Re-renderizado directo** desde el editor sin volver a la CLI.

### 13.2 Layout Split-Screen

Nuevo modo de renderizado para formatos verticales:

- **Gameplay arriba (60 %)**: Recorte centrado del source manteniendo relación de aspecto.
- **Cara abajo (40 %)**: Primer plano dinámico basado en detección facial MediaPipe.
- Ambas secciones provienen del **mismo video fuente**, por lo que el audio siempre está sincronizado.

### 13.3 Deduplicación Post-Editorial (E7.5)

Nueva etapa entre Director y TTS que evita renderizar clips duplicados:

- Calcula el rango de tiempo absoluto renderizado (`window_offset + trim`).
- Ordena por confianza de triage descendente.
- Aplica NMS con umbral IoU = 0.40.
- Reduce significativamente el tiempo y costo de render innecesario.

### 13.4 Soporte Docker Completo

- **Dockerfile multi-stage** basado en `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04`.
- **Docker Compose stack** con servicios: Redis, Qdrant, GUI (NiceGUI), Worker (arq).
- **Perfiles de setup** para descarga de modelos e inicialización de base de datos.
- Requiere NVIDIA Container Toolkit en el host.

### 13.5 Señales de Audio Mejoradas

- Detección de **risa** en el canal de audio (probabilidad por segundo).
- Señales de **chat** enriquecidas con análisis de emotes y sentimiento.

---

*Fin del Manual Técnico v1.1.*
