# AutoEdit AI — Manual de Usuario

**Versión:** 1.0  
**Fecha:** 2026-05-11  
**Autor:** Josemiguel Escobedo Checa  
**Audiencia:** Usuario final del sistema (creador de contenido).

---

## Tabla de Contenidos

1. [Introducción](#1-introducción)
2. [Flujo de Trabajo Diario](#2-flujo-de-trabajo-diario)
3. [Comandos CLI Principales](#3-comandos-cli-principales)
4. [Procesar VODs de Twitch](#4-procesar-vods-de-twitch)
5. [Procesar Videos Locales](#5-procesar-videos-locales)
6. [Gestión de Assets (Memes y SFX)](#6-gestión-de-assets-memes-y-sfx)
7. [Gestión de Perfiles de Voz](#7-gestión-de-perfiles-de-voz)
8. [Dashboard Web](#8-dashboard-web)
9. [Revisión y Rating de Clips](#9-revisión-y-rating-de-clips)
10. [Re-renderizado y Re-dirección](#10-re-renderizado-y-re-dirección)
11. [Comandos de Administración](#11-comandos-de-administración)
12. [Preguntas Frecuentes (FAQ)](#12-preguntas-frecuentes-faq)

---

## 1. Introducción

**AutoEdit AI** es tu asistente personal para convertir streams largos de Twitch en clips editados listos para subir a YouTube, TikTok, Instagram Reels y YouTube Shorts.

### ¿Qué hace el sistema?

1. **Descarga** tu VOD de Twitch (video + chat).
2. **Escucha y analiza** el audio, el chat y la transcripción para encontrar los mejores momentos.
3. **Clasifica** esos momentos por tipo: jugadas épicas, fails, reacciones divertidas, rage, etc.
4. **Edita automáticamente** cada clip con:
   - Subtítulos estilo karaoke (palabra por palabra).
   - Zooms dinámicos.
   - Memes y SFX sincronizados.
   - Narración con **tu propia voz clonada**.
5. **Renderiza** el video final en alta calidad con aceleración NVIDIA.

### Formatos de Salida

| Plataforma | Formato | Resolución |
|------------|---------|------------|
| YouTube | Horizontal | 1920×1080 (16:9) |
| TikTok / Reels / Shorts | Vertical | 1080×1920 (9:16) |

---

## 2. Flujo de Trabajo Diario

El uso típico del sistema sigue este flujo:

```
1. Terminas tu stream en Twitch
        ↓
2. Esperas ~5 minutos a que el VOD esté disponible
        ↓
3. Ejecutas: autoedit job add <URL_DEL_VOD>
        ↓
4. El sistema procesa automáticamente (15-45 min dependiendo de la duración)
        ↓
5. Abres el Dashboard: autoedit dashboard
        ↓
6. Revisas los clips generados, les das rating y descargas los mejores
        ↓
7. Subes a tus redes sociales
```

---

## 3. Comandos CLI Principales

AutoEdit se controla principalmente desde la terminal con el comando `autoedit`. A continuación los comandos más importantes:

### 3.1 Ayuda General

```bash
uv run autoedit --help
```

### 3.2 Verificación del Sistema

```bash
uv run autoedit doctor
```

Ejecuta una revisión completa: Python, GPU, Redis, Qdrant, FFmpeg, modelos descargados, perfil de voz y catálogo de assets.

### 3.3 Ping a OpenRouter

```bash
uv run autoedit ping
```

Verifica que la conexión con los servidores de IA funciona correctamente.

---

## 4. Procesar VODs de Twitch

### 4.1 Procesar un VOD Completo

```bash
uv run autoedit job add "URL_DEL_VOD" --clips 10 --lang es
```

**Parámetros:**
- `URL_DEL_VOD`: Enlace completo del VOD de Twitch.
- `--clips`: Cuántos clips quieres generar (default: 10, rango: 1-30).
- `--lang`: Idioma del stream (`es`, `en` o `auto`).

**Ejemplo:**

```bash
uv run autoedit job add "https://www.twitch.tv/videos/2184376591" --clips 8 --lang es
```

### 4.2 Qué sucede después de ejecutar `job add`

El sistema ejecuta automáticamente las etapas E0 a E4:
- Descarga el video y el chat.
- Extrae audio y detecta escenas.
- Transcribe todo el VOD.
- Analiza señales y encuentra los mejores momentos.

Al finalizar, verás un `job_id`. Úsalo para los siguientes pasos.

### 4.3 Continuar el Procesamiento Editorial

Para que el sistema aplique IA editorial (triage, director, TTS y render):

```bash
# Re-dirección editorial (E5-E8)
uv run autoedit job direct <JOB_ID>

# Renderizar clips finales (E9)
uv run autoedit render edit --job-id <JOB_ID>
```

Puedes obtener el `<JOB_ID>` con:

```bash
uv run autoedit job list
```

---

## 5. Procesar Videos Locales

Si tienes un video grabado localmente (no de Twitch):

```bash
uv run autoedit job local /ruta/al/video.mp4 --clips 5 --until e8
```

**Parámetros útiles:**
- `--clips`: Número de clips objetivo.
- `--until`: Hasta qué etapa ejecutar (`e1` a `e8`). Útil para pruebas.
- `--skip-tts`: Omite la generación de narración con voz clonada.
- `--lang`: Idioma del audio.

**Ejemplo de prueba rápida (hasta scoring):**

```bash
uv run autoedit job local ~/Videos/test.mp4 --clips 3 --until e4
```

---

## 6. Gestión de Assets (Memes y SFX)

Los **assets** son los elementos visuales y de audio que el sistema puede insertar en tus clips: memes, emotes, efectos de sonido (SFX) e imágenes.

### 6.1 Ingestar Assets Automáticamente

```bash
# Emotes de Twitch (BTTV, 7TV, FFZ) — no requieren API key
uv run autoedit assets ingest bttv 7tv ffz --limit 200

# Efectos de sonido de Freesound — requiere API key
uv run autoedit assets ingest freesound --limit 100

# Imágenes de Pixabay — requiere API key
uv run autoedit assets ingest pixabay --limit 100

# Todo a la vez
uv run autoedit assets ingest all
```

### 6.2 Ver el Catálogo

```bash
# Lista general
uv run autoedit assets list

# Estadísticas
uv run autoedit assets stats

# Búsqueda semántica
uv run autoedit assets search "fail funny" --kind image --top 5
uv run autoedit assets search "explosion dramatic" --kind sfx --top 3
```

### 6.3 Agregar Assets Manuales

Puedes copiar directamente tus propias imágenes y audios a:

- `data/assets/visual/` → Imágenes y memes (PNG, JPG, WEBP, MP4).
- `data/assets/audio/` → Efectos de sonido (WAV, MP3, OGG).

Luego reindexa para que el sistema los encuentre:

```bash
uv run autoedit assets reindex
```

---

## 7. Gestión de Perfiles de Voz

La voz clonada permite que el sistema narre tus clips con tu propia voz.

### 7.1 Registrar tu Voz

Necesitas un audio limpio de tu voz (mínimo 15 segundos, recomendado 30+).

```bash
uv run autoedit voice register ~/Audio/mi_voz.wav me_v1 --name "Mi Voz"
```

El sistema:
- Convierte el audio al formato correcto.
- Transcribe automáticamente lo que dices.
- Guarda el perfil para usarlo en todos los clips.

### 7.2 Listar Perfiles

```bash
uv run autoedit voice list
```

### 7.3 Probar tu Voz

```bash
uv run autoedit voice test "¡Qué jugada más increíble! Esto no me lo esperaba." me_v1
```

Se generará un archivo WAV en `data/voices/me_v1/test_*.wav`. Escúchalo con:

```bash
ffplay data/voices/me_v1/test_*.wav
```

### 7.4 Eliminar un Perfil

```bash
uv run autoedit voice delete me_v1
```

---

## 8. Dashboard Web

El Dashboard es una interfaz web para revisar clips sin usar la terminal.

### 8.1 Lanzar el Dashboard

```bash
uv run autoedit dashboard
```

Se abrirá automáticamente tu navegador en [http://localhost:7860](http://localhost:7860).

Para cambiar de puerto:

```bash
uv run autoedit dashboard --port 7861
```

Para no abrir el navegador automáticamente:

```bash
uv run autoedit dashboard --no-browser
```

### 8.2 Tabs del Dashboard

| Tab | Función |
|-----|---------|
| **📋 Jobs** | Ver todos los trabajos, su estado y etapa actual. |
| **🎞️ Clips Viewer** | Previsualizar clips, calificar con estrellas, agregar notas, re-renderizar. |
| **🎬 Re-direct** | Volver a generar decisiones editoriales (E6-E8) sin reprocesar el video. |

---

## 9. Revisión y Rating de Clips

### 9.1 Desde el Dashboard

1. Ve al tab **🎞️ Clips Viewer**.
2. Selecciona el **Job** de la lista desplegable.
3. Selecciona el **formato** (YouTube, TikTok, etc.).
4. Haz clic en **Load clips**.
5. Selecciona un clip de la lista para verlo.
6. Asigna un rating de 1 a 5 estrellas.
7. Agrega notas si deseas (ej. "Mejorar timing del zoom").
8. Guarda con **Save rating**.

### 9.2 Desde la Terminal

Los clips renderizados se guardan en:

```
data/vods/{vod_id}/clips/{clip_id}.mp4
```

Puedes listar los clips de un job con SQL directo o buscando en el directorio.

---

## 10. Re-renderizado y Re-dirección

### 10.1 ¿Cuándo Re-direccionar?

Si no te gustan las decisiones editoriales (memes elegidos, narración, zooms) pero el análisis base es bueno, puedes regenerar solo la parte editorial sin reprocesar horas de transcripción.

```bash
uv run autoedit job direct <JOB_ID>
```

**Opciones:**
- `--skip-tts`: Omite la regeneración de narraciones (más rápido).

### 10.2 Re-renderizar un Clip Específico

Desde el Dashboard, selecciona un clip y haz clic en **Re-render this clip**.

Desde la terminal:

```bash
uv run autoedit render edit --job-id <JOB_ID> --format youtube
uv run autoedit render edit --job-id <JOB_ID> --format tiktok
```

---

## 11. Comandos de Administración

### 11.1 Gestión de la Base de Datos

```bash
# Crear/actualizar tablas
uv run autoedit db migrate

# Resetear (⚠️ borra TODO)
uv run autoedit db reset

# Backup
uv run autoedit db backup
```

### 11.2 Listar Trabajos

```bash
# Todos los jobs
uv run autoedit job list

# Filtrar por estado
uv run autoedit job list --status failed
```

### 11.3 Ver Detalle de un Job

```bash
uv run autoedit job show <JOB_ID>
```

### 11.4 Worker en Segundo Plano

```bash
# Iniciar worker para procesar jobs encolados
make worker
```

---

## 12. Preguntas Frecuentes (FAQ)

### ¿Cuánto tarda en procesar un stream?

Depende de la duración y la GPU:

| Duración VOD | Tiempo Aproximado |
|--------------|-------------------|
| 1 hora | 15-25 minutos |
| 4 horas | 45-90 minutos |
| 8 horas | 90-180 minutos |

### ¿Cuánto cuesta usar la IA?

El sistema está diseñado para costar menos de **$0.20 USD por video** usando los modelos por defecto (DeepSeek V3 + Gemini Flash). Si usas modelos más caros (Claude, GPT-4o), el costo puede subir hasta ~$2.00.

### ¿Puedo usarlo sin GPU NVIDIA?

No recomendado. El sistema depende fuertemente de NVENC para renderizado rápido y de CUDA para Whisper, CLIP y F5-TTS. Sin GPU el procesamiento sería 10x más lento.

### ¿Dónde se guardan los clips finales?

```
data/vods/{vod_id}/clips/
```

Cada clip es un archivo `.mp4` listo para subir.

### ¿Puedo editar manualmente los clips después?

Sí. Los clips son archivos MP4 estándar. Puedes abrirlos en DaVinci Resolve, Premiere, CapCut o cualquier editor.

### ¿Qué pasa si se interrumpe el proceso?

Gracias al sistema de cacheo, puedes reanudar desde donde se quedó. Usa:

```bash
uv run autoedit job direct <JOB_ID>  # Para reanudar editorial
uv run autoedit render edit --job-id <JOB_ID>  # Para reanudar render
```

### ¿Cómo borro un VOD para liberar espacio?

Por defecto, el sistema borra el video fuente (`source.mp4`) automáticamente después de completar el job. Los clips finales se conservan.

Para borrar manualmente:

```bash
rm -rf data/vods/{vod_id}/source.mp4
```

### ¿Puedo procesar videos en inglés?

Sí. Usa `--lang en` al crear el job:

```bash
uv run autoedit job add <URL> --lang en
```

Whisper detectará automáticamente el idioma si usas `--lang auto`.

### ¿El sistema sube automáticamente a YouTube/TikTok?

No. AutoEdit AI genera los archivos MP4 localmente. Tú los subes manualmente a la plataforma que prefieras.

### ¿Cómo mejoro la calidad de los memes/SFX seleccionados?

Agrega más assets a tu catálogo:

1. Copia tus memes favoritos a `data/assets/visual/`.
2. Copia tus SFX favoritos a `data/assets/audio/`.
3. Reindexa: `uv run autoedit assets reindex`.

Cuanto más completo sea tu catálogo, mejores serán las coincidencias semánticas.

---

*Fin del Manual de Usuario.*
