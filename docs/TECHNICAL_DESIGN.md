# AutoEdit AI — Technical Design Document

**Versión:** 1.0
**Fecha:** 2026-05-10
**Autor:** Josemiguel Escobedo Checa (con asistencia de Claude)
**Estado:** Draft para implementación
**Audiencia:** Equipo de desarrollo (1-3 personas), futuro mantenedor

---

## Tabla de Contenidos

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Glosario](#2-glosario)
3. [Restricciones y Supuestos](#3-restricciones-y-supuestos)
4. [Arquitectura de Alto Nivel](#4-arquitectura-de-alto-nivel)
5. [Pipeline End-to-End](#5-pipeline-end-to-end)
6. [Modelo de Datos](#6-modelo-de-datos)
7. [Schemas Pydantic — Entidades del Dominio](#7-schemas-pydantic--entidades-del-dominio)
8. [Stack Tecnológico Definitivo](#8-stack-tecnológico-definitivo)
9. [Estructura de Directorios](#9-estructura-de-directorios)
10. [Gestión de Recursos GPU](#10-gestión-de-recursos-gpu)
11. [Especificación por Componente](#11-especificación-por-componente)
12. [Integración con OpenRouter (LLMs)](#12-integración-con-openrouter-llms)
13. [Layer de TTS (Voz Clonada)](#13-layer-de-tts-voz-clonada)
14. [Render con FFmpeg + NVENC](#14-render-con-ffmpeg--nvenc)
15. [CLI y Dashboard](#15-cli-y-dashboard)
16. [Observabilidad y Costos](#16-observabilidad-y-costos)
17. [Configuración y Secrets](#17-configuración-y-secrets)
18. [Testing](#18-testing)
19. [Deployment y Setup Local](#19-deployment-y-setup-local)
20. [Roadmap Detallado por Sprint](#20-roadmap-detallado-por-sprint)
21. [Riesgos y Mitigaciones](#21-riesgos-y-mitigaciones)
22. [Decisiones Pendientes / Asunciones](#22-decisiones-pendientes--asunciones)
23. [Apéndice A — Prompts](#apéndice-a--prompts)
24. [Apéndice B — Comandos FFmpeg de Referencia](#apéndice-b--comandos-ffmpeg-de-referencia)

---

## 1. Resumen Ejecutivo

**AutoEdit AI** convierte VODs largos de Twitch (1-8 h) en clips editados al estilo creator-comedy (zooms agresivos, memes, SFX, narración con voz clonada, subtítulos word-level estilo karaoke). El formato de salida principal es **YouTube (16:9)**; opcionalmente se generan versiones verticales **9:16** para Shorts de YouTube, TikTok y Reels a partir del mismo contenido. Diseñado como herramienta personal mono-tenant que corre **local-first** en una RTX 4070 mobile (8 GB VRAM) + i9-13980HX + 32 GB RAM, con LLMs accedidos vía **OpenRouter** (una API key) y todo lo demás self-hosted.

### Objetivos cuantitativos

| Métrica | Target |
|---------|--------|
| Tiempo de procesamiento por hora de VOD | ≤ 45 min |
| Volumen | 1 video procesado por día |
| Costo en LLM por video | < $0.20 (default) / < $2 (modo calidad) |
| Costo en infraestructura mensual | $0 (todo local + free tiers) |
| Clips por VOD | 5-15 candidatos finales |

### Estrategia central

1. **Cascada de señales**: filtros baratos (audio/chat/escenas) generan candidatos; el LLM solo ve top-N.
2. **GPU secuencial**: en 8 GB VRAM no caben Whisper + CLIP + TTS + render simultáneos. El scheduler corre **una etapa GPU-pesada a la vez**.
3. **Self-host por defecto**: Whisper, CLIP, CLAP, F5-TTS, Qdrant, todos locales.
4. **OpenRouter**: una sola integración HTTP para todos los LLM, default DeepSeek V3.
5. **CLI-first**: `autoedit` como CLI con Typer; dashboard Gradio para revisión visual.

---

## 2. Glosario

| Término | Definición |
|---------|------------|
| **VOD** | Video on Demand — grabación completa de un stream de Twitch |
| **Highlight** | Momento del VOD identificado como interesante (puede o no convertirse en clip) |
| **Clip** | Archivo MP4 final renderizado (16:9 o 9:16 según formato de salida), listo para subir |
| **Window** | Ventana temporal de 30-60 s extraída del VOD por el scoring |
| **Multiseñal** | Análisis combinado de audio, chat, escenas y transcripción sin LLM |
| **Triage** | Filtro VLM barato (Gemini Flash) sobre candidatos |
| **EditDecision** | JSON tipado emitido por el agente editorial; describe trim, memes, SFX, zooms, narración |
| **RAG de assets** | Búsqueda semántica de memes (CLIP) y SFX (CLAP) en Qdrant |
| **Reframe** | Crop dinámico que adapta el frame original al formato de salida (ej. 16:9 → 9:16) siguiendo al sujeto |
| **Burn-in** | Subtítulos quemados en el video (no sidecar SRT) |
| **Narración** | Audio TTS con voz clonada del creador, insertada entre cortes |
| **NVENC** | Encoder de hardware NVIDIA, en bloque separado del compute CUDA |
| **OpenRouter** | Gateway HTTP a múltiples LLM con una sola API key |

---

## 3. Restricciones y Supuestos

### Restricciones duras

- **Hardware fijo**: RTX 4070 Mobile (8 GB VRAM, NVENC8), i9-13980HX (24 cores), 32 GB DDR5 RAM, SSD NVMe local.
- **OS**: Ubuntu 22.04 LTS dentro de WSL2 sobre Windows 11. CUDA 12.x expuesto a WSL2 vía driver NVIDIA Windows.
- **Conectividad LLM**: exclusivamente OpenRouter (`https://openrouter.ai/api/v1`).
- **Mono-tenant**: un solo usuario (Josemiguel), sin auth/billing/quotas.
- **No comercial**: prioridad costo > calidad cuando hay tradeoff.

### Supuestos

- VRAM disponible para pipeline ≈ 7 GB (1 GB reservado para sistema/escritorio si Windows usa la GPU).
- Disco: ≥ 500 GB libres para VODs en proceso. VOD de 4 h ≈ 8-15 GB. Política: borrar VOD source tras generar todos los clips de ese job.
- Conexión: ≥ 100 Mbps para descarga de VOD (yt-dlp).
- El usuario provee un archivo `voice_ref.wav` de ≥ 30 s con audio limpio de su voz.
- El catálogo inicial de memes/SFX lo provee el usuario en `data/assets/visual/` y `data/assets/audio/` (formatos: PNG/JPG/WEBP/MP4 para visual, WAV/MP3/OGG para audio).

### Asunciones marcadas para validación (Resueltas)

Las siguientes decisiones han sido confirmadas y se aplican al diseño:

- **Idioma**: Soporte bilingüe español e inglés. El sistema debe detectar y procesar streams en cualquiera de estos idiomas (configurable por VOD o auto-detectado por Whisper).
- **Plataformas destino**:
  - **Principal**: YouTube (formato horizontal 16:9, 1920×1080).
  - **Derivados**: Shorts de YouTube, TikTok y Reels (formato vertical 9:16, 1080×1920). Se generan del mismo highlight seleccionado, adaptando el reframe y estilo.
- **Auto-upload**: No. El sistema solo genera archivos locales; el usuario los sube manualmente.
- **Duración objetivo del clip**: **45 segundos por defecto**, configurable por job en el rango 15-60 s.
- **Retención de VOD source**: Se borra automáticamente tras completar el job (`delete_source_after = True`) para liberar espacio en disco.
- **Trigger de jobs**: **Automático**. El sistema incluirá un poller que detecta nuevos VODs publicados en el canal de Twitch y los encola para procesamiento sin intervención manual. El modo manual (`autoedit job add <url>`) se mantiene para casos puntuales.
- **Catálogo inicial de assets**: El sistema inicia con catálogo vacío. El usuario agregará assets progresivamente vía CLI (`autoedit assets add`).
- **Estilo de subtítulos**: Adaptativo/configurable. No hay un estilo fijo por defecto; se seleccionará el que mejor se adecúe al formato de salida y preferencias del usuario.
- **Filtro de contenido**: Sin filtro de groserías ni contenido sensible.
- **Feedback loop**: Los ratings de clips se usan únicamente para evaluación y registro histórico. No afectan el modelo de scoring ni la toma de decisiones editorial de forma inmediata.

---

## 4. Arquitectura de Alto Nivel

### 4.1 Diagrama de componentes

```
┌──────────────────────────────────────────────────────────────────────┐
│                          USUARIO (Josemiguel)                         │
│              CLI (Typer)        ◄────►       Dashboard (Gradio)       │
└────────────────┬─────────────────────────────────────┬────────────────┘
                 │                                     │
                 ▼                                     ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    APPLICATION LAYER (Python 3.12)                    │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────┐  │
│  │  Pipeline    │  │  GPU         │  │  Cost & Trace Recorder     │  │
│  │  Orchestrator│◄─┤  Scheduler   │  │  (Langfuse SDK)            │  │
│  │  (Pydantic   │  │  (1 etapa    │  └────────────────────────────┘  │
│  │   AI graph)  │  │   GPU/vez)   │                                   │
│  └──────┬───────┘  └──────────────┘                                   │
│         │                                                             │
│         ▼                                                             │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  Domain Services                                                │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │   │
│  │  │Ingest  │ │Analyze │ │Score   │ │Triage  │ │Director│       │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘       │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                  │   │
│  │  │Retrieve│ │TTS     │ │Render  │ │Publish │                  │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘                  │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
└──┬────────────┬─────────────┬──────────────┬─────────────┬────────────┘
   │            │             │              │             │
   ▼            ▼             ▼              ▼             ▼
┌────────┐ ┌─────────┐  ┌─────────┐  ┌────────────┐  ┌──────────┐
│SQLite  │ │ Qdrant  │  │ Redis   │  │ Filesystem │  │OpenRouter│
│(estado │ │(vector  │  │(arq job │  │(VODs,clips,│  │(LLMs HTTP│
│ ops)   │ │  search)│  │ queue)  │  │ assets,    │  │ remoto)  │
│        │ │ Docker  │  │ Docker  │  │ models)    │  │          │
└────────┘ └─────────┘  └─────────┘  └────────────┘  └──────────┘
```

### 4.2 Procesos en runtime

- **CLI / Dashboard**: dispara y monitorea jobs.
- **Worker arq** (proceso Python long-lived): consume cola, ejecuta pipeline.
- **Redis** (Docker): backend de arq + cache de resultados intermedios.
- **Qdrant** (Docker): búsqueda vectorial de assets.
- **FFmpeg** (subprocess invocado por el worker): render usando NVENC.

Solo **un worker** corre a la vez (1 video/día). Si el usuario encola varios, se procesan en serie.

---

## 5. Pipeline End-to-End

### 5.1 Etapas y dependencias

```
[E0 INGEST]
   │ ├─► download_vod      (yt-dlp)        I/O bound
   │ └─► download_chat     (chat-downloader) I/O bound
   │     │
   │     ▼
[E1 EXTRACT]
   │ ├─► extract_audio     (FFmpeg, CPU)
   │ └─► detect_scenes     (PySceneDetect, CPU)
   │     │
   │     ▼
[E2 TRANSCRIBE]                           GPU: faster-whisper (~3 GB)
   │ └─► transcribe + word align (WhisperX)
   │     │
   │     ▼
[E3 ANALYZE]                              CPU paralelo
   │ ├─► audio_signals     (librosa, pyloudnorm)
   │ ├─► chat_signals      (density, keywords)
   │ └─► transcript_signals (kw spikes, sentiment)
   │     │
   │     ▼
[E4 SCORE]                                CPU
   │ └─► fuse_signals → top-N WindowCandidate
   │     │
   │     ▼
[E5 TRIAGE]                               LLM (Gemini Flash vía OpenRouter)
   │ └─► clasifica intención por candidato; descarta falsos positivos
   │     │
   │     ▼
[E6 RETRIEVE]                             GPU: CLIP+CLAP (~2 GB) → Qdrant
   │ └─► para cada highlight: top-K memes y top-J SFX
   │     │
   │     ▼
[E7 DIRECT]                               LLM (DeepSeek V3 default)
   │ └─► EditDecision tipada por highlight
   │     │
   │     ▼
[E8 TTS]                                  GPU: F5-TTS (~4 GB)
   │ └─► narraciones con voz clonada (cache por hash)
   │     │
   │     ▼
[E9 RENDER]                               GPU: NVENC (encoder dedicado)
    │ └─► trim + reframe al formato de salida + overlays + subs + narración
   │     │
   │     ▼
[E10 FINALIZE]
   │ └─► write metadata, opcional upload a R2
   │
   ▼
[DONE]
```

### 5.2 Idempotencia y cacheo

Cada etapa escribe artefactos a disco (`data/vods/{vod_id}/...`) y registra `RunStep` en SQLite. Re-ejecutar una etapa:

1. Verifica si artefacto existe + hash de inputs coincide.
2. Si sí → skip, marca `cached=true`.
3. Si no → ejecuta y guarda.

Esto permite reanudar jobs interrumpidos sin perder trabajo.

### 5.3 Orden GPU (crítico — ver §10)

```
E2 (Whisper)  →  liberar VRAM  →
E6 (CLIP+CLAP) → liberar VRAM  →
E8 (F5-TTS)   →  liberar VRAM  →
E9 (NVENC, no compite)
```

E5 y E7 son llamadas HTTP a OpenRouter (no usan GPU local).

---

## 6. Modelo de Datos

Tres almacenes:

1. **SQLite** (`data/autoedit.db`) — estado operacional, metadata, costos.
2. **Qdrant** (Docker, puerto 6333) — vectores para RAG de assets.
3. **Filesystem** (`data/`) — binarios (videos, audio, modelos, cache).

### 6.1 SQLite — DDL completo

ORM: **SQLModel** (sobre SQLAlchemy + Pydantic).

```sql
-- =========================
-- 6.1.1 jobs
-- =========================
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,             -- ULID
    vod_url         TEXT NOT NULL,                -- URL Twitch
    vod_id          TEXT,                         -- FK a vods.id (nullable hasta E0)
    status          TEXT NOT NULL,                -- queued|running|paused|done|failed|cancelled
    current_stage   TEXT,                         -- E0..E10
    config          TEXT NOT NULL,                -- JSON: JobConfig (clip_max_duration, target_count, llm_overrides…)
    error           TEXT,                         -- traceback si failed
    created_at      TEXT NOT NULL,                -- ISO8601 UTC
    started_at      TEXT,
    finished_at     TEXT,
    total_cost_usd  REAL DEFAULT 0.0,
    FOREIGN KEY (vod_id) REFERENCES vods(id) ON DELETE SET NULL
);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);

-- =========================
-- 6.1.2 vods
-- =========================
CREATE TABLE vods (
    id              TEXT PRIMARY KEY,             -- twitch_vod_id (numérico string)
    url             TEXT NOT NULL UNIQUE,
    title           TEXT,
    streamer        TEXT,
    duration_sec    REAL NOT NULL,
    recorded_at     TEXT,                         -- timestamp del stream
    language        TEXT DEFAULT 'auto',          -- BCP-47: es | en | auto (Whisper auto-detect)
    source_path     TEXT,                         -- relpath a data/vods/{id}/source.mp4
    audio_path      TEXT,                         -- data/vods/{id}/audio.wav
    chat_path       TEXT,                         -- data/vods/{id}/chat.jsonl
    source_size_mb  REAL,
    deleted_source  INTEGER DEFAULT 0,            -- 1 si ya borrado para liberar disco
    metadata        TEXT,                         -- JSON adicional (game, viewers_avg, etc.)
    created_at      TEXT NOT NULL
);

-- =========================
-- 6.1.3 run_steps
-- =========================
CREATE TABLE run_steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL,
    stage           TEXT NOT NULL,                -- E0..E10
    status          TEXT NOT NULL,                -- pending|running|done|failed|skipped|cached
    input_hash      TEXT,                         -- sha256 de inputs serializados
    output_path     TEXT,                         -- artefacto principal
    started_at      TEXT,
    finished_at     TEXT,
    duration_sec    REAL,
    cost_usd        REAL DEFAULT 0.0,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    model           TEXT,                         -- si LLM step
    error           TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE INDEX idx_run_steps_job ON run_steps(job_id, stage);

-- =========================
-- 6.1.4 transcript_segments
-- =========================
CREATE TABLE transcript_segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vod_id          TEXT NOT NULL,
    start_sec       REAL NOT NULL,
    end_sec         REAL NOT NULL,
    text            TEXT NOT NULL,
    speaker         TEXT,                         -- diarization label si disponible
    avg_logprob     REAL,                         -- confianza Whisper
    FOREIGN KEY (vod_id) REFERENCES vods(id) ON DELETE CASCADE
);
CREATE INDEX idx_transcript_vod_time ON transcript_segments(vod_id, start_sec);

-- =========================
-- 6.1.5 transcript_words
-- =========================
CREATE TABLE transcript_words (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id      INTEGER NOT NULL,
    word            TEXT NOT NULL,
    start_sec       REAL NOT NULL,
    end_sec         REAL NOT NULL,
    score           REAL,
    FOREIGN KEY (segment_id) REFERENCES transcript_segments(id) ON DELETE CASCADE
);
CREATE INDEX idx_words_segment ON transcript_words(segment_id);

-- =========================
-- 6.1.6 chat_messages    (puede ser MUCHO volumen — ver alternativa)
-- =========================
CREATE TABLE chat_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vod_id          TEXT NOT NULL,
    timestamp_sec   REAL NOT NULL,                -- offset desde inicio del VOD
    user            TEXT NOT NULL,
    message         TEXT NOT NULL,
    is_emote_only   INTEGER DEFAULT 0,
    FOREIGN KEY (vod_id) REFERENCES vods(id) ON DELETE CASCADE
);
CREATE INDEX idx_chat_vod_time ON chat_messages(vod_id, timestamp_sec);

-- ALTERNATIVA recomendada: si chat > 100k mensajes, mover a Parquet
-- en data/vods/{vod_id}/chat.parquet y solo agregar contadores en SQL.

-- =========================
-- 6.1.7 windows                         (candidatos generados por scoring)
-- =========================
CREATE TABLE windows (
    id              TEXT PRIMARY KEY,             -- ULID
    job_id          TEXT NOT NULL,
    vod_id          TEXT NOT NULL,
    start_sec       REAL NOT NULL,
    end_sec         REAL NOT NULL,
    score           REAL NOT NULL,                -- 0..1 fusión
    score_breakdown TEXT NOT NULL,                -- JSON: {audio:0.7, chat:0.5, scene:0.3, transcript:0.4}
    rank            INTEGER NOT NULL,             -- posición en top-N
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (vod_id) REFERENCES vods(id) ON DELETE CASCADE
);
CREATE INDEX idx_windows_job_rank ON windows(job_id, rank);

-- =========================
-- 6.1.8 highlights                      (post-triage, ya con intención)
-- =========================
CREATE TABLE highlights (
    id              TEXT PRIMARY KEY,             -- ULID
    window_id       TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    intent          TEXT NOT NULL,                -- fail|win|reaction|rage|funny_moment|skill_play|wholesome|other
    triage_confidence REAL NOT NULL,              -- 0..1
    triage_reasoning TEXT,                        -- texto del LLM
    discarded       INTEGER DEFAULT 0,            -- 1 si triage lo descartó
    discard_reason  TEXT,
    FOREIGN KEY (window_id) REFERENCES windows(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE INDEX idx_highlights_job ON highlights(job_id);

-- =========================
-- 6.1.9 edit_decisions                  (output del Director)
-- =========================
CREATE TABLE edit_decisions (
    id              TEXT PRIMARY KEY,             -- ULID
    highlight_id    TEXT NOT NULL UNIQUE,
    plan            TEXT NOT NULL,                -- JSON: EditDecision (ver §7.5)
    model           TEXT NOT NULL,                -- "deepseek/deepseek-chat-v3"
    cost_usd        REAL NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (highlight_id) REFERENCES highlights(id) ON DELETE CASCADE
);

-- =========================
-- 6.1.10 clips                          (output final renderizado)
-- =========================
CREATE TABLE clips (
    id              TEXT PRIMARY KEY,             -- ULID
    highlight_id    TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    output_path     TEXT NOT NULL,                -- data/vods/{vod_id}/clips/{clip_id}.mp4
    duration_sec    REAL NOT NULL,
    width           INTEGER NOT NULL,             -- 1080
    height          INTEGER NOT NULL,             -- 1920
    fps             REAL NOT NULL,                -- 30 o 60
    codec           TEXT NOT NULL,                -- h264_nvenc | hevc_nvenc | av1_nvenc
    file_size_mb    REAL,
    sha256          TEXT,
    rendered_at     TEXT NOT NULL,
    user_rating     INTEGER,                      -- 1-5 desde dashboard, null si no calificado
    user_note       TEXT,
    FOREIGN KEY (highlight_id) REFERENCES highlights(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE INDEX idx_clips_job ON clips(job_id);

-- =========================
-- 6.1.11 assets                         (catálogo de memes y SFX)
-- =========================
CREATE TABLE assets (
    id              TEXT PRIMARY KEY,             -- ULID o slug
    kind            TEXT NOT NULL,                -- visual_image|visual_video|audio_sfx
    file_path       TEXT NOT NULL,                -- data/assets/visual/xxx.png
    sha256          TEXT NOT NULL,
    duration_sec    REAL,                         -- null para imágenes
    width           INTEGER,
    height          INTEGER,
    sample_rate_hz  INTEGER,                      -- audio
    tags            TEXT NOT NULL,                -- JSON array: ["fail","dramatic","oof"]
    intent_affinity TEXT NOT NULL,                -- JSON array: ["fail","rage"] — para qué intent sirve
    description     TEXT,                         -- texto curado para embedding
    embedding_indexed INTEGER DEFAULT 0,          -- 1 si ya hay vector en Qdrant
    license         TEXT,                         -- "CC0"|"fair_use_personal"|"owned"
    source_url      TEXT,
    added_at        TEXT NOT NULL
);
CREATE INDEX idx_assets_kind ON assets(kind);

-- =========================
-- 6.1.12 asset_usages                   (qué asset se usó dónde)
-- =========================
CREATE TABLE asset_usages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id        TEXT NOT NULL,
    clip_id         TEXT NOT NULL,
    timeline_start  REAL NOT NULL,                -- offset dentro del clip
    timeline_end    REAL NOT NULL,
    role            TEXT NOT NULL,                -- meme_overlay|sfx|background_music
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
);
CREATE INDEX idx_usage_asset ON asset_usages(asset_id);
CREATE INDEX idx_usage_clip ON asset_usages(clip_id);

-- =========================
-- 6.1.13 narrations                     (cache de TTS)
-- =========================
CREATE TABLE narrations (
    id              TEXT PRIMARY KEY,             -- sha256(text + voice_id) primero 16 chars
    text            TEXT NOT NULL,
    voice_id        TEXT NOT NULL,                -- "me_v1"
    audio_path      TEXT NOT NULL,                -- data/cache/tts/{id}.wav
    duration_sec    REAL NOT NULL,
    sample_rate_hz  INTEGER NOT NULL,             -- 24000
    model           TEXT NOT NULL,                -- "f5-tts-v1.0"
    generated_at    TEXT NOT NULL,
    used_count      INTEGER DEFAULT 0
);
CREATE INDEX idx_narrations_voice ON narrations(voice_id);

-- =========================
-- 6.1.14 cost_entries                   (granular para análisis)
-- =========================
CREATE TABLE cost_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT,
    stage           TEXT,
    provider        TEXT NOT NULL,                -- openrouter|local
    model           TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    usd             REAL NOT NULL,
    occurred_at     TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL
);
CREATE INDEX idx_cost_job ON cost_entries(job_id);
```

### 6.2 Qdrant — Collections

| Collection | Vector dim | Distance | Payload schema |
|------------|-----------|----------|----------------|
| `assets_visual` | 512 (CLIP ViT-B/32) | Cosine | `{asset_id: str, tags: [str], intent_affinity: [str], kind: str}` |
| `assets_audio` | 512 (LAION-CLAP) | Cosine | `{asset_id: str, tags: [str], intent_affinity: [str], duration_sec: float}` |
| `transcript_chunks` | 384 (BGE-small es) | Cosine | `{vod_id, start_sec, end_sec, text}` (opcional, para búsqueda contextual a futuro) |

**Índice en filtros**: indexar `intent_affinity` y `tags` como keyword payload index para filtros rápidos durante búsqueda.

### 6.3 Filesystem — Layout

```
data/
├── autoedit.db                          # SQLite
├── vods/
│   └── {vod_id}/
│       ├── source.mp4                   # Original (puede borrarse post-job)
│       ├── audio.wav                    # 16kHz mono, para Whisper
│       ├── chat.jsonl                   # uno por línea: {ts, user, msg, emotes}
│       ├── transcript.json              # WhisperX output completo
│       ├── scenes.json                  # PySceneDetect output
│       ├── signals.parquet              # señales por segundo (ver §11.4)
│       ├── narrations/                  # TTS específico al VOD
│       │   └── {narration_id}.wav
│       └── clips/
│           ├── {clip_id}.mp4
│           ├── {clip_id}.ass            # subs estilizados
│           └── {clip_id}.meta.json      # EditDecision aplicada (auditoría)
├── assets/
│   ├── visual/
│   │   ├── {asset_id}.png
│   │   └── ...
│   └── audio/
│       ├── {asset_id}.wav
│       └── ...
├── voice_ref/
│   └── me.wav                           # ≥30s, 24kHz mono
├── cache/
│   ├── tts/                             # narraciones reusables global
│   │   └── {hash16}.wav
│   ├── triage/                          # respuestas de Gemini Flash cacheadas
│   │   └── {hash}.json
│   └── embeddings/
│       └── ...
├── models/                              # gitignored, descargados al setup
│   ├── faster-whisper-large-v3/
│   ├── wav2vec2-align-models/             # WhisperX align: spanish & english downloaded on demand
│   ├── clip-vit-b-32/
│   ├── laion-clap/
│   └── f5-tts/
└── tmp/                                 # workspace de FFmpeg, limpiable
```

**Política de retención (default)**:
- VOD source: borrar tras job done (settear `vods.deleted_source=1`).
- Audio.wav, transcripción, scenes, signals, chat: retener (son chicos, útiles para reanalizar).
- Clips: retener indefinidamente.
- Cache TTS: TTL 90 días, LRU si excede 5 GB.

---

## 7. Schemas Pydantic — Entidades del Dominio

Ubicación: `src/autoedit/domain/`. Todas las entidades tienen `model_config = ConfigDict(frozen=True)` salvo cuando se necesite mutación explícita.

### 7.1 Identificadores

```python
# src/autoedit/domain/ids.py
from typing import NewType
from ulid import ULID

JobId = NewType("JobId", str)
VodId = NewType("VodId", str)
WindowId = NewType("WindowId", str)
HighlightId = NewType("HighlightId", str)
ClipId = NewType("ClipId", str)
AssetId = NewType("AssetId", str)

def new_id() -> str:
    return str(ULID())
```

### 7.2 Job y configuración

```python
# src/autoedit/domain/job.py
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field

class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Stage(StrEnum):
    INGEST = "E0_ingest"
    EXTRACT = "E1_extract"
    TRANSCRIBE = "E2_transcribe"
    ANALYZE = "E3_analyze"
    SCORE = "E4_score"
    TRIAGE = "E5_triage"
    RETRIEVE = "E6_retrieve"
    DIRECT = "E7_direct"
    TTS = "E8_tts"
    RENDER = "E9_render"
    FINALIZE = "E10_finalize"

class JobConfig(BaseModel):
    target_clip_count: int = Field(default=10, ge=1, le=30)
    clip_min_duration_sec: float = 15.0
    clip_max_duration_sec: float = 45.0
    output_formats: list[str] = Field(default_factory=lambda: ["youtube"])  # "youtube" (16:9) | "short" (9:16)
    output_resolution: tuple[int, int] = (1920, 1080)        # Default YouTube 16:9
    output_fps: int = 30
    output_codec: str = "h264_nvenc"                         # h264_nvenc|hevc_nvenc|av1_nvenc
    enable_narration: bool = True
    enable_memes: bool = True
    enable_sfx: bool = True
    director_model: str = "deepseek/deepseek-chat-v3"
    triage_model: str = "google/gemini-2.5-flash"
    language: str = "es"                                     # "es" | "en" | "auto"
    delete_source_after: bool = True

class Job(BaseModel):
    id: JobId
    vod_url: str
    vod_id: VodId | None = None
    status: JobStatus
    current_stage: Stage | None = None
    config: JobConfig
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_cost_usd: float = 0.0
```

### 7.3 Señales y ventanas

```python
# src/autoedit/domain/signals.py
from pydantic import BaseModel, Field

class AudioSignal(BaseModel):
    """Una entrada por segundo del VOD."""
    t_sec: float
    rms_db: float
    loudness_lufs: float
    pitch_hz: float | None = None
    laughter_prob: float = Field(ge=0.0, le=1.0, default=0.0)

class ChatSignal(BaseModel):
    t_sec: float
    msg_per_sec: float
    unique_users: int
    keyword_score: float                     # 0..1 normalizado por LUL/F/Pog/etc.
    sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)

class SceneSignal(BaseModel):
    t_sec: float
    is_cut: bool
    shot_id: int

class WindowCandidate(BaseModel):
    id: WindowId
    vod_id: VodId
    start_sec: float
    end_sec: float
    score: float = Field(ge=0.0, le=1.0)
    score_breakdown: dict[str, float]        # {"audio":..,"chat":..,"scene":..,"transcript":..}
    rank: int
    transcript_excerpt: str                  # texto Whisper de esa ventana
```

### 7.4 Triage y highlights

```python
# src/autoedit/domain/highlight.py
from enum import StrEnum
from pydantic import BaseModel, Field

class Intent(StrEnum):
    FAIL = "fail"
    WIN = "win"
    REACTION = "reaction"
    RAGE = "rage"
    FUNNY_MOMENT = "funny_moment"
    SKILL_PLAY = "skill_play"
    WHOLESOME = "wholesome"
    OTHER = "other"

class TriageResult(BaseModel):
    """Output del Triage VLM (Gemini Flash)."""
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    keep: bool
    reasoning: str = Field(max_length=500)

class Highlight(BaseModel):
    id: HighlightId
    window_id: WindowId
    job_id: JobId
    intent: Intent
    triage_confidence: float
    triage_reasoning: str
    discarded: bool = False
    discard_reason: str | None = None
```

### 7.5 EditDecision (output del Director)

Esta es **la entidad más crítica del sistema**. Es lo que el agente editorial debe emitir como JSON estricto.

```python
# src/autoedit/domain/edit_decision.py
from pydantic import BaseModel, Field
from enum import StrEnum

class ZoomKind(StrEnum):
    SUBJECT_FACE = "subject_face"            # zoom siguiendo cara
    REGION = "region"                        # zoom a región fija
    PUNCH_IN = "punch_in"                    # zoom rápido binario

class Trim(BaseModel):
    start_sec: float                         # absolute en VOD
    end_sec: float
    reason: str = Field(max_length=200)

class ZoomEvent(BaseModel):
    at_sec: float                            # relativo al inicio del clip ya trimmed
    duration_sec: float = Field(ge=0.1, le=5.0)
    kind: ZoomKind
    intensity: float = Field(ge=1.0, le=2.5)  # 1.0 = no zoom, 2.5 = punch
    region: tuple[float, float, float, float] | None = None  # (x,y,w,h) normalizado 0-1, si kind=REGION

class MemeOverlay(BaseModel):
    asset_id: AssetId
    at_sec: float                            # relativo al clip
    duration_sec: float = Field(ge=0.3, le=8.0)
    position: str = Field(default="center")  # center|top|bottom|top_left|...
    scale: float = Field(default=0.4, ge=0.1, le=1.0)  # fracción del ancho
    enter_anim: str = "pop"                  # pop|fade|slide_in
    exit_anim: str = "fade"

class SfxCue(BaseModel):
    asset_id: AssetId
    at_sec: float
    volume_db: float = Field(default=-6.0, ge=-30.0, le=6.0)

class NarrationCue(BaseModel):
    text: str = Field(max_length=300)
    at_sec: float                            # cuándo empezar la narración
    voice_id: str = "me_v1"
    duck_main_audio_db: float = -10.0        # cuánto bajar audio original mientras habla

class SubtitleStyle(BaseModel):
    font_family: str = "Arial Black"
    font_size_px: int = 72
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_px: int = 4
    position: str = "lower_third"            # lower_third|center|upper_third
    karaoke_highlight_color: str = "#FFD700"

class EditDecision(BaseModel):
    """Plan completo para renderizar un highlight."""
    highlight_id: HighlightId
    title: str = Field(max_length=80)        # para metadata/upload futuro
    trim: Trim
    zoom_events: list[ZoomEvent] = Field(default_factory=list, max_length=15)
    meme_overlays: list[MemeOverlay] = Field(default_factory=list, max_length=8)
    sfx_cues: list[SfxCue] = Field(default_factory=list, max_length=10)
    narration_cues: list[NarrationCue] = Field(default_factory=list, max_length=4)
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    background_music_asset_id: AssetId | None = None
    rationale: str = Field(max_length=600)   # explicación del director, útil para evals
```

**JSON Schema** se genera con `EditDecision.model_json_schema()` y se inyecta al prompt del Director (modo response_format=json_schema en OpenRouter cuando el modelo lo soporta — DeepSeek y Claude sí).

### 7.6 Clip y assets

```python
# src/autoedit/domain/clip.py
class Clip(BaseModel):
    id: ClipId
    highlight_id: HighlightId
    job_id: JobId
    output_path: str
    duration_sec: float
    width: int
    height: int
    fps: float
    codec: str
    file_size_mb: float | None = None
    sha256: str | None = None
    rendered_at: datetime
    user_rating: int | None = None
    user_note: str | None = None

# src/autoedit/domain/asset.py
class AssetKind(StrEnum):
    VISUAL_IMAGE = "visual_image"
    VISUAL_VIDEO = "visual_video"
    AUDIO_SFX = "audio_sfx"

class Asset(BaseModel):
    id: AssetId
    kind: AssetKind
    file_path: str
    sha256: str
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    sample_rate_hz: int | None = None
    tags: list[str]
    intent_affinity: list[Intent]
    description: str | None = None
    license: str = "owned"
    source_url: str | None = None
```

---

## 8. Stack Tecnológico Definitivo

| Capa | Tecnología | Versión | Notas |
|------|------------|---------|-------|
| Lenguaje | Python | 3.12+ | uv para deps |
| Package mgr | uv | latest | `uv sync`, `uv run` |
| Type validation | Pydantic | 2.x | `pydantic-settings` para config |
| ORM | SQLModel | latest | sobre SQLAlchemy 2.x |
| DB | SQLite | 3.45+ | WAL mode habilitado |
| Vector DB | Qdrant | 1.11+ Docker | `qdrant/qdrant:latest` |
| Job queue | arq | 0.26+ | asyncio, Redis backend |
| Cache/Broker | Redis | 7.x Docker | `redis:7-alpine` |
| HTTP client | httpx | 0.27+ | async, timeouts explícitos |
| LLM gateway | OpenRouter | — | OpenAI-compatible API |
| LLM SDK | openai | 1.x | apunta a OpenRouter base_url |
| Agente editorial | Pydantic AI | 0.0.x latest | sobre el cliente OpenAI |
| CLI | Typer | 0.12+ | + rich para output |
| Dashboard | Gradio | 4.x | tabs: jobs, clips, assets, costs |
| Logging | loguru | 0.7+ | JSON sink + console |
| Tracing LLM | langfuse | 2.x | cloud free tier |
| Test | pytest | 8.x | + pytest-asyncio + pytest-cov |
| Lint/format | ruff | latest | replace black+isort+flake8 |
| Type check | mypy | 1.x | strict mode |
| **Video/Audio** | | | |
| FFmpeg | FFmpeg | 7.x con NVENC | system binary |
| Video editing | ffmpeg-python | latest | wrapper liviano |
| VOD download | yt-dlp | latest | actualizar mensualmente |
| Twitch chat | chat-downloader | latest | Twitch GraphQL backed |
| Audio analysis | librosa | 0.10+ | + soundfile, pyloudnorm |
| Scene detection | PySceneDetect | 0.6+ | `detect-content` |
| Face tracking | mediapipe | 0.10+ | Face Detection + Mesh |
| **ML local** | | | |
| Transcripción | faster-whisper | 1.0+ | large-v3, int8 |
| Word alignment | whisperx | 3.x | wav2vec2 align per detected lang (es/en) |
| Image embeddings | open_clip_torch | 2.x | ViT-B-32 |
| Audio embeddings | laion-clap | 1.x | 630k_audioset |
| TTS | F5-TTS | 1.x | voice cloning |
| ML runtime | torch | 2.4+ | CUDA 12.1 build |

---

## 9. Estructura de Directorios

```
autoedit-ai/
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── README.md
├── Makefile
├── compose.yml                          # Redis + Qdrant + Langfuse opcional
│
├── src/autoedit/
│   ├── __init__.py
│   ├── settings.py                      # pydantic-settings (env)
│   │
│   ├── domain/                          # Entidades Pydantic, sin lógica
│   │   ├── __init__.py
│   │   ├── ids.py
│   │   ├── job.py
│   │   ├── signals.py
│   │   ├── highlight.py
│   │   ├── edit_decision.py
│   │   ├── clip.py
│   │   └── asset.py
│   │
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py              # Pydantic AI graph que enlaza nodos
│   │   ├── state.py                     # PipelineState compartido entre nodos
│   │   ├── gpu_scheduler.py             # mutex global GPU
│   │   ├── caching.py                   # input_hash + skip si artefacto OK
│   │   └── nodes/
│   │       ├── e0_ingest.py
│   │       ├── e1_extract.py
│   │       ├── e2_transcribe.py
│   │       ├── e3_analyze.py
│   │       ├── e4_score.py
│   │       ├── e5_triage.py
│   │       ├── e6_retrieve.py
│   │       ├── e7_direct.py
│   │       ├── e8_tts.py
│   │       ├── e9_render.py
│   │       └── e10_finalize.py
│   │
│   ├── ingest/
│   │   ├── twitch_vod.py                # yt-dlp wrapper, yields progress
│   │   └── twitch_chat.py               # chat-downloader wrapper
│   │
│   ├── analysis/
│   │   ├── audio.py                     # rms, loudness, laughter
│   │   ├── chat.py                      # density, kw spikes, emote rate
│   │   ├── scenes.py                    # PySceneDetect facade
│   │   ├── transcript_signals.py        # kw spikes en transcripción, sentiment
│   │   ├── transcribe.py                # faster-whisper + WhisperX align
│   │   └── face_tracker.py              # mediapipe wrapper
│   │
│   ├── scoring/
│   │   ├── fusion.py                    # weights, peak detection, NMS
│   │   └── windowing.py                 # extracción de ventanas top-N
│   │
│   ├── editorial/
│   │   ├── triage.py                    # llamadas a Gemini Flash con vision
│   │   ├── director.py                  # Pydantic AI agent → EditDecision
│   │   └── prompts/
│   │       ├── triage_es.md
│   │       ├── director_es.md
│   │       └── narration_es.md
│   │
│   ├── assets/
│   │   ├── ingest_indexer.py            # CLI: añadir assets nuevos al catálogo
│   │   ├── retrieval.py                 # búsqueda híbrida (vector + filtros)
│   │   ├── catalog.py                   # CRUD sobre tabla assets
│   │   └── deduplication.py             # evitar reusar mismo meme N veces seguidas
│   │
│   ├── tts/
│   │   ├── f5_engine.py                 # wrapper F5-TTS
│   │   ├── voice_cloning.py             # carga + cache de voice profile
│   │   └── narration_cache.py           # SQLite + filesystem
│   │
│   ├── render/
│   │   ├── ffmpeg_runner.py             # subprocess.run + progress parsing
│   │   ├── reframe.py                   # 16:9 → 9:16 con face tracking + Kalman
│   │   ├── subtitles.py                 # WhisperX → ASS karaoke estilizado
│   │   ├── compositor.py                # EditDecision → command line FFmpeg
│   │   └── filters/                     # filter_complex helpers
│   │       ├── overlay.py
│   │       ├── zoom.py
│   │       └── audio_mix.py
│   │
│   ├── llm/
│   │   ├── openrouter.py                # cliente HTTP único
│   │   ├── pricing.py                   # tabla de precios por modelo
│   │   └── retry.py                     # backoff exponencial, circuit breaker
│   │
│   ├── storage/
│   │   ├── db.py                        # engine SQLModel
│   │   ├── repositories/                # un módulo por agregado
│   │   │   ├── jobs.py
│   │   │   ├── vods.py
│   │   │   ├── windows.py
│   │   │   ├── highlights.py
│   │   │   ├── clips.py
│   │   │   ├── assets.py
│   │   │   ├── narrations.py
│   │   │   └── costs.py
│   │   ├── files.py                     # paths helpers, retention
│   │   └── qdrant.py                    # cliente + collection mgmt
│   │
│   ├── observability/
│   │   ├── logging.py                   # loguru config
│   │   ├── tracing.py                   # langfuse spans
│   │   └── metrics.py                   # contadores in-process
│   │
│   ├── workers/
│   │   ├── worker.py                    # arq WorkerSettings
│   │   └── tasks.py                     # task: process_job(job_id)
│   │
│   ├── cli/
│   │   ├── main.py                      # typer App
│   │   ├── commands/
│   │   │   ├── job.py                   # autoedit job add|list|cancel|retry
│   │   │   ├── render.py                # autoedit render --highlight-id
│   │   │   ├── assets.py                # autoedit assets add|reindex|search
│   │   │   ├── voice.py                 # autoedit voice register --file me.wav
│   │   │   ├── db.py                    # autoedit db migrate|reset|backup
│   │   │   └── doctor.py                # health check (Redis, Qdrant, GPU, models)
│   │   └── progress.py                  # rich progress bars
│   │
│   ├── dashboard/
│   │   ├── app.py                       # gradio Blocks
│   │   ├── pages/
│   │   │   ├── jobs.py                  # listado, status, costos
│   │   │   ├── clips.py                 # preview, rate, regenerar
│   │   │   ├── assets.py                # browse + add
│   │   │   └── settings.py              # ver config, cambiar default model
│   │   └── components/
│   │       └── video_player.py
│   │
│   └── evals/
│       ├── reference_set.py             # carga clips de referencia anotados
│       ├── metrics.py                   # IoU temporal, intent F1, calidad heurística
│       └── runner.py                    # CLI: autoedit evals run
│
├── tests/
│   ├── unit/
│   │   ├── domain/                      # propiedades de schemas
│   │   ├── scoring/                     # casos sintéticos de fusión
│   │   ├── editorial/                   # mocks de OpenRouter
│   │   └── render/                      # generación de comandos FFmpeg
│   ├── integration/
│   │   ├── test_pipeline_short_vod.py   # fixture 30s VOD reducido
│   │   └── test_db_migrations.py
│   ├── conftest.py
│   └── fixtures/
│       ├── short_vod.mp4                # 30s sintético
│       ├── short_chat.jsonl
│       └── voice_ref.wav
│
├── infra/
│   ├── compose.yml -> ../compose.yml
│   ├── qdrant_init.py                   # crea collections vacías
│   └── download_models.py               # descarga Whisper, CLIP, F5-TTS, etc.
│
├── docs/
│   ├── TECHNICAL_DESIGN.md              # este documento
│   ├── ADR/                             # Architecture Decision Records
│   ├── PROMPTS.md                       # versionado de prompts
│   └── RUNBOOK.md                       # operación, troubleshooting
│
└── data/                                # gitignored (excepto .gitkeep)
    └── (ver §6.3)
```

---

## 10. Gestión de Recursos GPU

### 10.1 El problema

8 GB VRAM y modelos grandes que no caben juntos:

| Modelo | VRAM aprox |
|--------|-----------|
| faster-whisper large-v3 (int8) | 3.0 GB |
| WhisperX align (wav2vec2) | 1.5 GB |
| open_clip ViT-B/32 | 0.6 GB |
| LAION-CLAP | 1.0 GB |
| F5-TTS | 4.0 GB |
| FFmpeg con NVENC | <0.5 GB compute (encoder dedicado) |

Whisper + CLIP cabe (~5 GB). Whisper + F5-TTS NO cabe. CLIP + F5-TTS justo (~4.6 GB).

### 10.2 Solución — `GpuScheduler`

Mutex async global. Cada nodo declara qué modelos necesita. El scheduler:

1. Verifica si los modelos requeridos están cargados.
2. Si no caben con lo cargado → descarga (`torch.cuda.empty_cache()` + `del model`) los de menor prioridad.
3. Carga los nuevos.
4. Adquiere mutex compute (no NVENC).
5. Ejecuta callback.
6. Libera mutex.

```python
# src/autoedit/pipeline/gpu_scheduler.py — pseudocódigo
class GpuScheduler:
    def __init__(self, max_vram_mb: int = 7000):
        self._loaded: dict[str, ModelHandle] = {}
        self._compute_lock = asyncio.Lock()
        self._budget = max_vram_mb

    async def with_models(self, models: list[ModelSpec], fn):
        await self._ensure_loaded(models)
        async with self._compute_lock:
            return await fn(self._loaded)

    async def _ensure_loaded(self, specs):
        # evict LRU si no cabe
        ...
```

NVENC opera fuera del lock — el render puede empezar mientras se preparan los siguientes recursos del próximo job (no aplica a 1 video/día pero deja la puerta abierta).

### 10.3 Política de carga por etapa

| Etapa | Modelos que carga | Modelos que descarga |
|-------|-------------------|----------------------|
| E2 transcribe | whisper, whisperx_align | — |
| E5 triage | (HTTP, no GPU) | whisper, whisperx_align |
| E6 retrieve | clip, clap | — (whisper ya descargado) |
| E7 direct | (HTTP, no GPU) | — |
| E8 tts | f5_tts | clip, clap |
| E9 render | NVENC (no compute) | f5_tts |

---

## 11. Especificación por Componente

### 11.1 E0 Ingest

**Inputs**: `vod_url: str`
**Outputs**: `data/vods/{vod_id}/source.mp4`, `data/vods/{vod_id}/chat.jsonl`, registro en `vods`.

**Implementación**:

```python
# Subprocess con yt-dlp
yt-dlp \
  --format "best[ext=mp4]/best" \
  --output "data/vods/{vod_id}/source.%(ext)s" \
  --no-progress \
  --print-json \
  {vod_url}
```

Capturar JSON de salida → extraer `id`, `duration`, `title`, `uploader`, `upload_date`.

Chat:
```python
chat_downloader = ChatDownloader()
chat = chat_downloader.get_chat(vod_url)
with open("chat.jsonl", "w") as f:
    for msg in chat:
        f.write(json.dumps({
            "ts": msg["time_in_seconds"],
            "user": msg["author"]["name"],
            "msg": msg["message"],
            "emotes": [e["name"] for e in msg.get("emotes", [])],
        }) + "\n")
```

**Errores manejados**:
- VOD privado / 404 → `JobFailed("vod_unavailable")`.
- Disco lleno → liberar `data/tmp/` y reintentar 1×, luego fallar.
- Timeout > 1 h → fallar con backoff sugerido.

### 11.2 E1 Extract

**Outputs**: `audio.wav` (16 kHz, mono, PCM), `scenes.json`.

```bash
# Audio
ffmpeg -i source.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le audio.wav

# Scenes (Python)
from scenedetect import detect, ContentDetector
scenes = detect("source.mp4", ContentDetector(threshold=27.0))
# Persistir como [{shot_id, start_sec, end_sec, is_cut: True}]
```

### 11.3 E2 Transcribe

```python
from faster_whisper import WhisperModel
model = WhisperModel(
    "large-v3",
    device="cuda",
    compute_type="int8_float16",
    download_root="data/models/faster-whisper-large-v3",
)
segments, info = model.transcribe(
    "audio.wav",
    language="es",  # Use "auto" or None for bilingual detection; override via JobConfig
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 500},
    beam_size=5,
)
```

Después WhisperX para alignment word-level:

```python
import whisperx
align_model, metadata = whisperx.load_align_model(language_code="es", device="cuda")  # Dynamically load es/en based on detected language
aligned = whisperx.align(segments, align_model, metadata, "audio.wav", device="cuda")
```

**Persistencia**: dump completo a `transcript.json` (formato WhisperX) + insertar en `transcript_segments` y `transcript_words`.

### 11.4 E3 Analyze (señales paralelas)

Output canónico: `signals.parquet` con schema:

| col | tipo | descripción |
|-----|------|-------------|
| `t_sec` | float | inicio del bin (1 s) |
| `audio_rms_db` | float | |
| `audio_loudness_lufs` | float | |
| `laughter_prob` | float | 0..1, opcional (Sprint 6+) |
| `chat_msg_per_sec` | float | |
| `chat_unique_users` | int | |
| `chat_kw_score` | float | normalizado (LUL, F, OMEGALUL, Pog…) |
| `chat_emote_rate` | float | proporción de mensajes con emote |
| `transcript_kw_score` | float | spike en palabras clave del streamer |
| `is_scene_cut` | bool | |

Resolución: 1 bin por segundo. VOD de 4 h = 14 400 filas, ~200 KB en parquet.

### 11.5 E4 Score

```python
# Pesos default (afinables)
WEIGHTS = {
    "audio": 0.35,
    "chat": 0.30,
    "transcript": 0.20,
    "scene": 0.15,
}

# Para cada segundo, normalizar señales → 0..1 (z-score clipped + sigmoid)
# Score por segundo = sum(w_i * normalized_i)
# Aplicar smoothing (rolling mean ventana 5 s)
# Peak detection: scipy.signal.find_peaks con prominence
# Convertir cada peak a Window (start = peak - 25s, end = peak + 25s)
# NMS temporal: si dos windows overlap > 30%, mantener la de mayor score
# Retornar top-N (default N=20)
```

### 11.6 E5 Triage (LLM Vision — Gemini Flash)

Para cada `WindowCandidate`:

1. Extraer 4 frames muestreados uniformemente del segmento (FFmpeg).
2. Construir prompt multimodal (ver Apéndice A.1).
3. Enviar a `google/gemini-2.5-flash` vía OpenRouter con `response_format=json_schema`.
4. Parsear `TriageResult`. Si `keep=False` → marcar `discarded`.

**Cache**: key = sha256(vod_id + start_sec + end_sec + transcript_excerpt + model). TTL 30 días.

**Costo estimado**: 4 frames + ~500 tokens texto = ~1500 tokens input × 50 windows = 75k tokens. A $0.075/M = ~$0.006/job.

### 11.7 E6 Retrieve (RAG assets)

Para cada Highlight kept:

```python
# Construir query
query_text = f"{highlight.intent} reaction meme. Context: {transcript_excerpt}"

# Visual
img_emb = clip.encode_text(query_text)
results = qdrant.search(
    collection="assets_visual",
    query_vector=img_emb,
    limit=10,
    query_filter=Filter(
        must=[FieldCondition(key="intent_affinity", match=MatchAny(any=[highlight.intent]))]
    ),
)
# Deduplicar contra usados recientemente (asset_usages últimas 48h)
top_memes = filter_recent_usage(results)[:5]

# Audio
audio_emb = clap.encode_text(query_text)
top_sfx = qdrant.search("assets_audio", audio_emb, limit=5, ...)
```

### 11.8 E7 Direct (Editorial agentic)

Pydantic AI Agent con DeepSeek V3 default.

```python
from pydantic_ai import Agent

director = Agent(
    "openai:deepseek/deepseek-chat-v3",   # via OpenRouter base_url
    result_type=EditDecision,
    system_prompt=load_prompt("director_es.md"),
)

result = await director.run(
    user_prompt=build_director_prompt(highlight, transcript, top_memes, top_sfx),
)
edit_decision = result.data  # EditDecision Pydantic
```

El prompt incluye:
- Intención y contexto del highlight (transcript de la ventana ±10 s extra).
- Lista de memes candidatos con `id`, `description`, `tags`.
- Lista de SFX candidatos similares.
- Preferencias de estilo del usuario (config).
- JSON Schema de EditDecision.

### 11.9 E8 TTS

Para cada `NarrationCue` en el `EditDecision`:

```python
hash_id = hashlib.sha256(f"{cue.text}|{cue.voice_id}".encode()).hexdigest()[:16]
cached = narration_cache.get(hash_id)
if cached:
    return cached.audio_path

audio = f5_tts.generate(
    text=cue.text,
    voice_ref="data/voice_ref/me.wav",
    speed=1.0,
    seed=42,                              # reproducibilidad
)
audio_path = f"data/cache/tts/{hash_id}.wav"
sf.write(audio_path, audio, 24000)
narration_cache.save(hash_id, audio_path, ...)
```

### 11.10 E9 Render

Ver §14 — sección dedicada.

### 11.11 E10 Finalize

- Calcular `sha256` y `file_size_mb` de cada clip.
- Insertar en `clips`.
- Si `config.delete_source_after` → borrar `source.mp4`, marcar `vods.deleted_source=1`.
- Emitir evento `JobDone` (log + actualizar status).
- Opcional: subir a R2 (Sprint 8+).

---

## 12. Integración con OpenRouter (LLMs)

### 12.1 Cliente

```python
# src/autoedit/llm/openrouter.py
from openai import AsyncOpenAI
from autoedit.settings import settings

client = AsyncOpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": "https://github.com/josemiguel/autoedit-ai",
        "X-Title": "AutoEdit AI",
    },
    timeout=120.0,
)
```

### 12.2 Modelos por etapa (defaults)

| Etapa | Modelo | Razón | Precio aprox (in/out per 1M) |
|-------|--------|-------|------------------------------|
| Triage VLM | `google/gemini-2.5-flash` | Vision barato, latencia baja | $0.075 / $0.30 |
| Director | `deepseek/deepseek-chat-v3` | JSON estricto, razonamiento, barato | $0.27 / $1.10 |
| Director (upgrade manual) | `anthropic/claude-sonnet-4-6` | Calidad creativa | $3 / $15 |
| Director (premium) | `anthropic/claude-opus-4-7` | Solo casos especiales | $15 / $75 |

### 12.3 Retry y rate limits

- Retry: backoff exponencial 1s, 2s, 4s, 8s, 16s. Max 5 intentos.
- Errores reintentables: 429, 502, 503, 504, network errors.
- No reintentar: 400 (input malformado), 401 (auth), 422 (validación).
- Circuit breaker: si 10 fallas consecutivas en 1 min → pausar pipeline 5 min.

### 12.4 Costos: registro

Cada llamada LLM produce un `cost_entries`:

```python
async def call_llm_with_tracking(model, messages, **kwargs):
    response = await client.chat.completions.create(model=model, messages=messages, **kwargs)
    usd = pricing.estimate(model, response.usage.prompt_tokens, response.usage.completion_tokens)
    await cost_repo.record(job_id=ctx.job_id, stage=ctx.stage, model=model,
                           tokens_in=response.usage.prompt_tokens,
                           tokens_out=response.usage.completion_tokens, usd=usd)
    return response
```

---

## 13. Layer de TTS (Voz Clonada)

### 13.1 F5-TTS setup

```python
from f5_tts.api import F5TTS

engine = F5TTS(
    model_type="F5-TTS",
    ckpt_file="data/models/f5-tts/model_1200000.safetensors",
    vocab_file="data/models/f5-tts/vocab.txt",
    device="cuda",
)
```

### 13.2 Voice profile

El usuario corre una sola vez:

```bash
autoedit voice register --file data/voice_ref/me.wav --voice-id me_v1
```

Esto valida (≥30 s, mono, sin ruido excesivo) y persiste el path en `data/voice_profiles.json`.

### 13.3 Generación

```python
audio_arr, sample_rate, _ = engine.infer(
    ref_file="data/voice_ref/me.wav",
    ref_text="",                  # F5-TTS hace ASR del ref si no se da
    gen_text=cue.text,
    speed=1.0,
    nfe_step=32,                  # más alto = mejor calidad, más lento
    seed=42,
)
sf.write(out_path, audio_arr, sample_rate)
```

### 13.4 Ducking del audio principal

Cuando hay narración, el audio del clip se atenúa ese intervalo. Implementado en el filter_complex de FFmpeg con `volume` + `acrossfade` (ver Apéndice B).

---

## 14. Render con FFmpeg + NVENC

### 14.1 Pipeline de render

Para cada `EditDecision`:

```
1. Trim source.mp4 → segment.mp4               (FFmpeg seek + copy si posible)
2. Reframe 9:16 con face tracking              (filter complex con crop dinámico)
3. Overlay memes (PNG/MP4) timeline-driven     (filter overlay con enable=between(t,a,b))
4. Generar subs ASS desde transcript words     (subtitles burn-in)
5. Mezcla audio: original + narración + SFX    (amix + ducking)
6. Encode NVENC final                          (h264_nvenc preset p4 cq=22)
```

### 14.2 Comando representativo

```bash
ffmpeg -y \
  -hwaccel cuda -hwaccel_output_format cuda \
  -ss {trim_start} -to {trim_end} -i source.mp4 \
  -i meme1.png -i meme2.mp4 \
  -i narration.wav -i sfx1.wav \
  -filter_complex "
    [0:v]hwdownload,format=nv12,
         crop={crop_w}:{crop_h}:{crop_x}:{crop_y},
         scale=1080:1920,
         zoompan=z='if(between(t,2,3),min(zoom+0.05,1.5),1)':
                d=1:s=1080x1920[v0];
    [1:v]scale=iw*0.4:-1[m1];
    [v0][m1]overlay=W*0.3:H*0.7:enable='between(t,1.5,3.5)'[v1];
    [v1]subtitles='subs.ass'[vout];
    [0:a]volume=enable='between(t,5,7)':volume=0.3[a0];
    [3:a]adelay=5000|5000[narr];
    [4:a]adelay=2000|2000[sfx];
    [a0][narr][sfx]amix=inputs=3:duration=longest[aout]
  " \
  -map "[vout]" -map "[aout]" \
  -c:v h264_nvenc -preset p4 -tune hq -rc vbr -cq 22 -b:v 8M \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  output.mp4
```

### 14.3 Reframe inteligente

Algoritmo:
1. Para cada frame muestreado a 5 fps: detectar cara con MediaPipe.
2. Si encuentra cara dominante → centro de crop = centro de la cara.
3. Si no → centro de crop = centro del frame original (fallback).
4. Suavizar trayectoria con filtro de Kalman (var posición = 50 px², var velocidad = 5 px²).
5. Generar curva paramétrica `crop_x(t)`, `crop_y(t)` que el filter_complex consume.

Ancho del crop: `crop_w = int(input_h * 9 / 16)`. Alto = input_h.

### 14.4 Subtítulos ASS karaoke

Generados desde `transcript_words` recortados al rango del clip:

```
[Script Info]
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Outline, Shadow, Alignment, MarginV
Style: Default,Arial Black,72,&H00FFFFFF,&H00000000,4,1,2,200

[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.50,0:00:02.10,Default,{\k50}HOLA {\k30}A {\k60}TODOS
```

`\kNN` define la duración por palabra para el efecto karaoke.

---

## 15. CLI y Dashboard

### 15.1 CLI — comandos

```bash
# Health
autoedit doctor                          # check Redis, Qdrant, GPU, modelos descargados

# Setup
autoedit db migrate
autoedit voice register --file me.wav --voice-id me_v1
autoedit assets add --dir ./mis_memes --kind visual_image --tags fail,oof
autoedit assets reindex                  # reconstruye Qdrant desde tabla assets

# Jobs
autoedit job add <vod_url> [--config job.yaml]
autoedit job list [--status running]
autoedit job show <job_id>
autoedit job cancel <job_id>
autoedit job retry <job_id> [--from-stage E5]

# Render manual / debug
autoedit render --highlight-id <hid> --regen-edit-decision
autoedit triage --window-id <wid>

# Worker
autoedit worker run                      # arranca arq worker

# Dashboard
autoedit dashboard                       # gradio en http://localhost:7860

# Evals
autoedit evals run --set ./evals/reference_v1
```

### 15.2 Dashboard — pestañas

1. **Jobs**: tabla con status, costo acumulado, etapa actual, botón cancel/retry.
2. **Clips**: grid con preview de cada clip, rating 1-5, nota, botones "regenerar render", "regenerar EditDecision con upgrade model".
3. **Assets**: browse del catálogo, búsqueda, agregar nuevo asset.
4. **Settings**: ver config global, cambiar default models, ver health.

---

## 16. Observabilidad y Costos

### 16.1 Logging

`loguru` con dos sinks:
- Console: nivel INFO, formato humano-legible, color.
- Archivo `data/logs/autoedit.jsonl`: nivel DEBUG, JSON estructurado, rotación diaria, retención 14 días.

Cada log incluye `job_id`, `stage`, `vod_id` cuando aplique (via `logger.bind`).

### 16.2 Tracing

Langfuse cloud (free tier suficiente para 1 video/día):

```python
from langfuse import Langfuse, observe

@observe(name="director_call")
async def call_director(highlight, ...):
    ...
```

Cada call LLM genera un span con tokens y costo. Trace completo del job navegable en UI Langfuse.

### 16.3 Costos

Vista SQL ya integrada:

```sql
-- Costo por job
SELECT j.id, j.vod_url, j.total_cost_usd,
       SUM(CASE WHEN c.stage='E5_triage' THEN c.usd ELSE 0 END) AS triage_cost,
       SUM(CASE WHEN c.stage='E7_direct' THEN c.usd ELSE 0 END) AS director_cost
FROM jobs j LEFT JOIN cost_entries c ON c.job_id = j.id
GROUP BY j.id;
```

Dashboard expone esta vista.

---

## 17. Configuración y Secrets

### 17.1 `pydantic-settings`

```python
# src/autoedit/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # LLM
    OPENROUTER_API_KEY: str

    # Storage
    DATA_DIR: str = "./data"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"

    # GPU
    GPU_VRAM_BUDGET_MB: int = 7000

    # Defaults LLM
    DIRECTOR_MODEL: str = "deepseek/deepseek-chat-v3"
    TRIAGE_MODEL: str = "google/gemini-2.5-flash"

    # Observability
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # FFmpeg
    FFMPEG_BIN: str = "ffmpeg"
    NVENC_PRESET: str = "p4"
    NVENC_CQ: int = 22

settings = Settings()
```

### 17.2 `.env.example`

Generar copiando `.env.example` → `.env` y rellenando.

---

## 18. Testing

### 18.1 Pirámide

- **Unit (60%)**: lógica pura — fusion, prompts builder, FFmpeg command generator, schemas.
- **Integration (30%)**: pipeline en VOD sintético de 30 s con LLMs mockeados.
- **End-to-end (10%)**: corrida real opcional con un VOD chico (semanal en CI manual).

### 18.2 Fixtures clave

- `tests/fixtures/short_vod.mp4` — 30 s sintéticos con 1 "pico" claro (audio loud + chat density alto en la marca 15s).
- `tests/fixtures/short_chat.jsonl` — chat alineado al pico.
- `tests/fixtures/voice_ref.wav` — 35 s de voz sintética (ej. con `pyttsx3`).
- `tests/fixtures/asset_pack/` — 5 memes + 5 SFX libres.

### 18.3 Mocks

- OpenRouter: `respx` para HTTPX. Snapshots de respuestas en `tests/snapshots/`.
- F5-TTS: stub que genera silencio de la duración correcta (no carga modelo).
- Qdrant: usar Qdrant en memoria (`:memory:` mode) durante tests.

### 18.4 Coverage objetivo

- Unit: ≥85%.
- Integration: ≥70% del path principal del pipeline.

---

## 19. Deployment y Setup Local

### 19.1 Requisitos del host

- Windows 11 + WSL2 con Ubuntu 22.04.
- Driver NVIDIA Windows ≥ 555.x.
- Docker Desktop con WSL2 backend.
- Python 3.12 en WSL.
- FFmpeg con NVENC (compilar o `apt install ffmpeg` con build con `--enable-nvenc`).

### 19.2 Bootstrap (`Makefile`)

```makefile
.PHONY: setup
setup: install-uv install-deps download-models init-db init-qdrant
	@echo "✅ Setup completo. Corre 'make up' para servicios."

install-uv:
	curl -LsSf https://astral.sh/uv/install.sh | sh

install-deps:
	uv sync

download-models:
	uv run python infra/download_models.py

init-db:
	uv run autoedit db migrate

init-qdrant:
	uv run python infra/qdrant_init.py

up:
	docker compose up -d redis qdrant

down:
	docker compose down

worker:
	uv run autoedit worker run

dashboard:
	uv run autoedit dashboard
```

### 19.3 `compose.yml`

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: ["./data/redis:/data"]
    command: redis-server --appendonly yes

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333", "6334:6334"]
    volumes: ["./data/qdrant:/qdrant/storage"]
```

### 19.4 Verificación post-setup

```bash
make setup && make up
uv run autoedit doctor
# Expected:
# ✓ Python 3.12.x
# ✓ Redis reachable at localhost:6379
# ✓ Qdrant reachable at localhost:6333
# ✓ GPU detected: NVIDIA RTX 4070 Laptop, 8 GB
# ✓ NVENC available: h264_nvenc, hevc_nvenc, av1_nvenc
# ✓ Models downloaded: faster-whisper-large-v3, clip-vit-b-32, f5-tts, ...
# ✓ Voice profile registered: me_v1
# ✓ Catálogo de assets: 0 visual, 0 audio  ⚠ vacío
```

---

## 20. Roadmap Detallado por Sprint

Cada sprint = ~1 semana de trabajo part-time. Cada sprint termina con un demo ejecutable y tests verdes.

### Sprint 0 — Fundación (3-4 días)

**Scope**:
- Repo + uv + ruff + mypy + pytest configurado.
- `compose.yml` + `Makefile` funcionales.
- `settings.py` cargando `.env`.
- `autoedit doctor` que verifica servicios y GPU.
- `autoedit db migrate` crea SQLite con todas las tablas.
- Cliente OpenRouter con `autoedit ping --model deepseek/deepseek-chat-v3` que hace una llamada hello-world.
- CI básico (GitHub Actions): ruff + mypy + pytest unit.

**Criterio de aceptación**:
```bash
make setup && make up && uv run autoedit doctor && uv run autoedit ping
# Todo verde, costo de ping registrado en cost_entries.
```

### Sprint 1 — Ingesta + Análisis multiseñal

**Scope**:
- E0 ingest: yt-dlp + chat-downloader, persistencia en `vods` y filesystem.
- E1 extract: audio + scenes.
- E2 transcribe: faster-whisper + WhisperX align.
- E3 analyze: 4 señales en `signals.parquet`.
- E4 score: fusión, NMS, top-N.
- CLI: `autoedit job add`, `autoedit job show`.
- Worker arq corriendo el pipeline hasta E4.

**Criterio**:
```bash
autoedit job add https://twitch.tv/videos/XXX
# Tras ~20 min: status=done, top 20 windows en SQLite, transcript completo.
```

### Sprint 2 — Render mínimo viable

**Scope**:
- E9 render con: trim simple + crop 9:16 estático centrado + subtítulos ASS karaoke + NVENC.
- Sin agentic; recibe lista de `(start, end)` y produce MP4s.
- Reframe centrado (no inteligente todavía).
- CLI: `autoedit render --windows-from-job <jid> --top 5`.

**Criterio**: 5 clips MP4 9:16 con subs estilizados se generan en <10 min para un VOD ya analizado.

### Sprint 3 — TTS voz clonada

**Scope**:
- F5-TTS integrado con cache.
- `autoedit voice register`.
- E8 narration: dado un `EditDecision` con `narration_cues`, generar WAVs.
- Mezcla de narración con audio original (ducking) en el render.
- Test integración: clip con narración audible.

**Criterio**: clip con narración insertada al segundo 5, audio original baja -10 dB durante la narración, cache reusa narraciones idénticas.

### Sprint 4 — RAG de assets

**Scope**:
- `autoedit assets add` indexa imagen/audio en Qdrant + tabla.
- Embeddings: CLIP para visual, CLAP para audio.
- E6 retrieve: búsqueda híbrida con filtros de intent.
- Deduplicación contra usos recientes.
- CLI: `autoedit assets search "fail dramatic" --kind visual`.

**Criterio**: dado un `Highlight` con intent=fail, el sistema retorna 5 memes relevantes que no se usaron en las últimas 48 h.

### Sprint 5 — Triage + Director

**Scope**:
- E5 triage con Gemini Flash + extracción de 4 frames.
- E7 director con Pydantic AI + DeepSeek V3 + JSON Schema strict.
- Pipeline end-to-end: VOD URL → clips finales con memes/SFX/narración.

**Criterio**: `autoedit job add <url>` corre todo y produce 5-10 clips automáticos. Costo total <$0.50.

### Sprint 6 — Reframe inteligente + zooms dinámicos

**Scope**:
- MediaPipe face detection en frames muestreados.
- Filtro Kalman para suavizado de trayectoria.
- Zooms dinámicos según `ZoomEvent` en `EditDecision`.

**Criterio**: en un clip con webcam, la cara siempre está en cuadro y los zooms se aplican en los momentos pedidos.

### Sprint 7 — Dashboard Gradio

**Scope**:
- Pestañas: Jobs, Clips (con preview), Assets, Settings.
- Acción "regenerar este clip con Claude Sonnet" (override del director).
- Rating 1-5 que se persiste para futuras evals.

**Criterio**: Josemiguel puede correr todo el flujo sin tocar la CLI.

### Sprint 8 — Evals + tuning

**Scope**:
- 10-20 clips de referencia anotados manualmente.
- Métricas: precisión de intent (vs anotación), IoU temporal (clip generado vs ideal), tasa de "no me gusta" (rating <3).
- Comparativo entre director models (DeepSeek vs Sonnet vs Opus) en el mismo set.
- ADR con la decisión final del modelo default.

**Criterio**: dashboard de evals, números reproducibles, decisión documentada.

---

## 21. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|-----------|
| FFmpeg+NVENC no cumple SLO de 45 min | Media | Alto | Sprint 2 incluye benchmark explícito. Si falla: bajar resolución a 720x1280 o usar `hevc_nvenc` que es más eficiente. |
| F5-TTS calidad insuficiente con voz del usuario | Media | Medio | Plan B: xTTS v2 (más maduro). Plan C: ElevenLabs (cuesta ~$5/mes). |
| OpenRouter rate limit / outage | Baja | Medio | Retry + circuit breaker + cache de triage. Para outage extendido: pausar pipeline. |
| VRAM insuficiente para alguna combinación | Media | Alto | GpuScheduler con eviction. Si no alcanza: degradar Whisper a `medium` o usar CPU para CLIP. |
| Calidad subjetiva de los clips | Alta | Alto | Sprint 8 con evals + opción de upgrade manual a Claude Sonnet/Opus. |
| Catálogo de assets muy chico | Alta | Medio | Documentar proceso de crecimiento; buscar packs CC0 (Mixkit, Freesound, etc.). |
| Disco lleno por VODs | Media | Medio | Política de retención + alerta si <50 GB libres. |
| Cambios en API de Twitch / yt-dlp | Media | Bajo | Pin de versiones + tests que se corren semanalmente contra un VOD público estable. |

---

## 22. Decisiones Resueltas / Asunciones

Las siguientes decisiones de diseño han sido validadas y congeladas. Cualquier cambio futuro requerirá un ADR.

| # | Decisión | Resolución | Impacto en el sistema |
|---|----------|------------|----------------------|
| A1 | Idioma del stream | **Bilingüe: español e inglés**. Whisper detectará el idioma automáticamente. Los prompts del Director y Triage deben soportar ambos idiomas o adaptarse según la transcripción. | Whisper `language=None` para auto-detect. Prompts con instrucciones bilingües o templates separados por idioma detectado. |
| A2 | Plataformas destino | **YouTube (16:9) como principal**. TikTok/Reels/Shorts (9:16) como derivados del mismo highlight. Se generan múltiples formatos por highlight si se configura. | El `JobConfig` incluirá `output_formats: list[Literal["youtube","short"]]`. El render genera variantes 16:9 y/o 9:16. |
| A3 | Auto-upload | **No**. Solo generación de archivos locales. | Sin integraciones de upload. Posible Sprint 9+ si cambia. |
| A4 | Duración del clip | **Default = 45 s**, configurable por job. | `JobConfig.clip_max_duration_sec = 45.0`. |
| A5 | Retención VOD source | **Borrar tras job done**. | `delete_source_after = True` por defecto. Política de liberación inmediata post-finalize. |
| A6 | Trigger de jobs | **Automático (poller) + Manual**. Un servicio de fondo detectará nuevos VODs del canal y los encolará. CLI `job add` se mantiene para VODs puntuales o externos. | Nuevo componente `src/autoedit/poller/` (Sprint 1 o 2). Necesita almacenar `last_checked_vod_id`. |
| A7 | Catálogo inicial de assets | **Vacío al inicio**. El usuario popula progresivamente. | Sin dependencia de assets para arrancar. Qdrant inicia con collections vacías. |
| A8 | Estilo de subtítulos | **Adaptativo / configurable**. No hay default rígido. | `SubtitleStyle` en `JobConfig` o `EditDecision` permite override. Se propondrán presets ("YouTube Classic", "Shorts Bold", etc.). |
| A9 | Filtro de contenido | **Sin filtro**. No se censuran groserías ni contenido sensible. | No se añade lógica de filtrado en prompts ni en post-procesamiento. |
| A10 | Ratings y feedback | **Solo para evaluación histórica**. No afectan el pipeline inmediato. | Tabla `clips.user_rating` se mantiene para análisis offline (Sprint 8). No hay feedback loop real-time. |

---

## Apéndice A — Prompts

### A.1 Triage (multimodal, Gemini Flash)

```
Eres un editor de video que evalúa momentos de un stream de Twitch para determinar
si vale la pena convertirlos en un clip destacado (highlight) para YouTube o sus derivados verticales.

Analiza estos 4 frames (uniformemente muestreados) y el siguiente contexto:

Streamer: {streamer_name}
Juego: {game_name}
Transcripción del momento ({duration:.1f}s):
"""
{transcript_excerpt}
"""

Mensajes destacados del chat en este intervalo:
{top_chat_messages}

Tu tarea: clasifica el momento en una de estas intenciones:
- fail (un error gracioso)
- win (una jugada victoriosa)
- reaction (reacción exagerada del streamer)
- rage (enojo cómico)
- funny_moment (chiste, comentario gracioso)
- skill_play (jugada técnicamente impresionante)
- wholesome (momento tierno/positivo)
- other

Y decide `keep`: ¿es un momento lo suficientemente fuerte para un short?

Responde estrictamente en este JSON (sin texto adicional):

{json_schema}
```

### A.2 Director (DeepSeek V3)

```
Eres el director editorial de un canal de highlights tipo ConnorDawg: cortes rápidos,
zooms agresivos, memes irónicos, narración punzante y timing cómico.

Estás editando este momento:
- Intención: {intent}
- Razón del triage: {triage_reasoning}
- Duración bruta: {duration:.1f}s
- Transcripción extendida (±10s):
"""
{extended_transcript}
"""

Memes disponibles (elige los que encajen, máx 3):
{candidate_memes_json}

SFX disponibles (elige los que encajen, máx 5):
{candidate_sfx_json}

Reglas:
1. El clip final debe durar entre {min}s y {max}s.
2. El trim debe empezar 1-2s antes del momento clave para contexto.
3. Si añades narración con voz del creador, máximo {max_narrations} cues, cada uno
   <= 8s, y debe complementar (no repetir) lo que ya se dice.
4. Memes overlay con duración 0.8-3s, casi siempre con animación 'pop' al entrar.
5. Zoom punch-in (intensity 1.8-2.3) en el frame exacto del clímax.
6. Subtítulos siempre en lower_third, fuente grande.

Devuelve EXCLUSIVAMENTE un JSON válido conforme a este schema:
{edit_decision_schema}

Incluye en `rationale` (max 600 chars) la explicación editorial de tus decisiones.
```

### A.3 Narration helper (futuro Sprint 5+)

(Si usamos un sub-agente para refinar el texto de narración antes de TTS)

```
Genera una línea de narración corta, en el idioma del stream (español MX o inglés según corresponda), irónica y seca, máx 12 palabras,
para este momento: {context}. Estilo: como un comentarista hartado pero cariñoso.
```

---

## Apéndice B — Comandos FFmpeg de Referencia

### B.1 Trim sin re-encoding (rápido pero menos preciso)

```bash
ffmpeg -y -ss 1234.5 -to 1289.0 -i source.mp4 -c copy segment.mp4
```

### B.2 Trim con re-encoding (preciso al frame)

```bash
ffmpeg -y -i source.mp4 -ss 1234.5 -to 1289.0 \
  -c:v h264_nvenc -preset p7 -cq 18 segment.mp4
```

### B.3 Crop dinámico simple (sin Kalman)

```bash
ffmpeg -i in.mp4 -vf "crop=607:1080:'(in_w-607)/2':0,scale=1080:1920" out.mp4
```

### B.4 Overlay PNG con ventana temporal

```bash
ffmpeg -i base.mp4 -i meme.png -filter_complex \
  "[1:v]scale=400:-1[m];[0:v][m]overlay=x=H*0.5-w/2:y=H*0.7:enable='between(t,3.5,5.0)'" \
  out.mp4
```

### B.5 Audio ducking durante narración

```bash
ffmpeg -i clip.mp4 -i narration.wav -filter_complex \
  "[0:a]volume=0.3:enable='between(t,5.0,8.5)'[a0]; \
   [1:a]adelay=5000|5000[narr]; \
   [a0][narr]amix=inputs=2:duration=longest[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac out.mp4
```

### B.6 Encode final con NVENC (preset balanceado)

```bash
ffmpeg -i in.mp4 -c:v h264_nvenc -preset p4 -tune hq \
  -rc vbr -cq 22 -b:v 8M -maxrate 12M -bufsize 16M \
  -c:a aac -b:a 192k -movflags +faststart out.mp4
```

---

**FIN DEL DOCUMENTO**

Para cambios futuros: crear ADR en `docs/ADR/NNNN-titulo.md` y actualizar la sección afectada de este TDD.
