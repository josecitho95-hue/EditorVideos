# AutoEdit AI — Manual de Usuario

**Versión:** 1.1  
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
8. [Editor Visual — NiceGUI](#8-editor-visual--nicegui)
9. [Dashboard Gradio](#9-dashboard-gradio)
10. [Revisión y Rating de Clips](#10-revisión-y-rating-de-clips)
11. [Re-renderizado y Re-dirección](#11-re-renderizado-y-re-dirección)
12. [Formatos de Salida y Layouts](#12-formatos-de-salida-y-layouts)
13. [Comandos de Administración](#13-comandos-de-administración)
14. [Preguntas Frecuentes (FAQ)](#14-preguntas-frecuentes-faq)
15. [Novedades v1.1](#15-novedades-v11)

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
6. **Deduplica** clips superpuestos para no generar contenido repetido.

### Formatos de Salida

| Plataforma | Formato | Resolución | Layout |
|------------|---------|------------|--------|
| YouTube | Horizontal | 1920×1080 (16:9) | crop (default) |
| TikTok / Reels / Shorts | Vertical | 1080×1920 (9:16) | crop o split |
| Instagram / Twitter | Cuadrado | 1080×1080 (1:1) | crop |

### Layout Split-Screen

Diseñado especialmente para TikTok/Reels/Shorts, el layout **split** divide la pantalla vertical en dos secciones usando **el mismo video fuente**:

- **Arriba (60 %)**: Gameplay con recorte centrado.
- **Abajo (40 %)**: Primer plano de tu cara, detectada automáticamente.

Esto mantiene el audio perfectamente sincronizado y no requiere cámara secundaria.

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
5. Abres el Editor: autoedit gui
        ↓
6. Revisas el timeline, ajustas efectos si lo deseas, y guardas
        ↓
7. Renderizas clips en YouTube y/o TikTok
        ↓
8. Subes a tus redes sociales
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

### 3.4 Interfaces Web

```bash
# Editor visual completo (NiceGUI) — recomendado
uv run autoedit gui

# Dashboard ligero (Gradio) — alternativa
uv run autoedit dashboard
```

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

## 8. Editor Visual — NiceGUI

El **Editor NiceGUI** es la interfaz principal recomendada para revisar y editar clips. Ofrece un timeline interactivo con control total sobre cada efecto.

### 8.1 Lanzar el Editor

```bash
uv run autoedit gui
```

Se abrirá automáticamente tu navegador en [http://localhost:7880](http://localhost:7880).

Para cambiar de puerto:

```bash
uv run autoedit gui --port 7881
```

Para no abrir el navegador automáticamente:

```bash
uv run autoedit gui --no-browser
```

### 8.2 Páginas del Editor

#### /jobs — Grid de Trabajos

- Visualiza todos tus jobs en tarjetas con color de estado.
- Cada tarjeta muestra: ID, estado, etapa actual, fecha de creación y URL del VOD.
- Haz clic en **"Ver Timeline"** para editar un job.
- Haz clic en **"Clips"** para ver los clips renderizados.

#### /timeline/{job_id} — Editor de Timeline

Esta es la página más potente del sistema. Permite editar visualmente las decisiones editoriales generadas por la IA.

**Sidebar izquierdo — Lista de Highlights:**
- Cada highlight muestra su intención (fail, win, rage, etc.) con color distintivo.
- Muestra confianza del triage, rango de tiempo y título.
- Haz clic en un highlight para cargar su timeline.

**Área principal — Timeline Canvas:**
- **Track Trim**: Arrastra los handles de inicio/fin para ajustar el corte del clip.
- **Track Zooms**: Bloques verdes representando zooms dinámicos. Arrastra para mover o redimensionar.
- **Track Memes**: Bloques rosas con memes superpuestos.
- **Track SFX**: Pines naranjas indicando efectos de sonido.
- **Track Narración**: Bloques púrpuras con el texto de narración.

**Panel de Propiedades:**
- Aparece al hacer clic en cualquier elemento del timeline.
- Permite editar valores numéricos (intensidad de zoom, volumen de SFX, etc.).
- Permite editar texto de narración.

**Botones de acción:**
- **Guardar**: Persiste los cambios en la base de datos.
- **Re-render**: Genera el clip MP4 con los cambios actuales (formato YouTube).
- **TikTok**: Genera el clip en formato vertical 9:16.
- **Split**: Genera el clip en formato split-screen (gameplay + cara).

> **Nota:** El timeline utiliza un canvas interactivo en JavaScript. Si aparece en blanco, recarga la página con Ctrl+F5.

#### /clips/{job_id} — Galería de Clips

- Muestra todos los clips renderizados para un job.
- **Stats bar**: Total, en disco, valorados.
- Cada tarjeta de clip muestra: duración, resolución, fecha de renderizado, rating con estrellas.
- **Acciones**:
  - **Abrir carpeta**: Abre el explorador de archivos en la carpeta del clip.
  - **Copiar ruta**: Copia la ruta del archivo al portapapeles.

---

## 9. Dashboard Gradio

El Dashboard Gradio es una interfaz más ligera y sencilla, útil para revisiones rápidas.

### 9.1 Lanzar el Dashboard

```bash
uv run autoedit dashboard
```

Abre automáticamente [http://localhost:7860](http://localhost:7860).

### 9.2 Tabs del Dashboard

| Tab | Función |
|-----|---------|
| **📋 Jobs** | Ver todos los trabajos, su estado y etapa actual. |
| **🎞️ Clips Viewer** | Previsualizar clips, calificar con estrellas, agregar notas, re-renderizar. |
| **🎬 Re-direct** | Volver a generar decisiones editoriales (E6-E8) sin reprocesar el video. |

---

## 10. Revisión y Rating de Clips

### 10.1 Desde el Editor NiceGUI

1. Ve a **/clips/{job_id}**.
2. Revisa las tarjetas de clips con sus metadatos.
3. Los clips renderizados muestran una badge verde "En disco".
4. El rating aparece como estrellas ★★★☆☆.

### 10.2 Desde el Dashboard Gradio

1. Ve al tab **🎞️ Clips Viewer**.
2. Selecciona el **Job** de la lista desplegable.
3. Selecciona el **formato** (YouTube, TikTok, etc.).
4. Haz clic en **Load clips**.
5. Selecciona un clip de la lista para verlo.
6. Asigna un rating de 1 a 5 estrellas.
7. Agrega notas si deseas (ej. "Mejorar timing del zoom").
8. Guarda con **Save rating**.

### 10.3 Desde la Terminal

Los clips renderizados se guardan en:

```
data/vods/{vod_id}/clips/{clip_id}.mp4
```

---

## 11. Re-renderizado y Re-dirección

### 11.1 ¿Cuándo Re-direccionar?

Si no te gustan las decisiones editoriales (memes elegidos, narración, zooms) pero el análisis base es bueno, puedes regenerar solo la parte editorial sin reprocesar horas de transcripción.

```bash
uv run autoedit job direct <JOB_ID>
```

**Opciones:**
- `--skip-tts`: Omite la regeneración de narraciones (más rápido).

### 11.2 Re-renderizar un Clip Específico

Desde el Editor NiceGUI, selecciona un highlight en el timeline y haz clic en **Re-render**, **TikTok** o **Split**.

Desde la terminal:

```bash
# YouTube (16:9)
uv run autoedit render edit --job-id <JOB_ID> --format youtube

# TikTok / Shorts (9:16)
uv run autoedit render edit --job-id <JOB_ID> --format tiktok

# Con layout split-screen
uv run autoedit render edit --job-id <JOB_ID> --format tiktok --layout split

# Cuadrado (1:1)
uv run autoedit render edit --job-id <JOB_ID> --format square
```

---

## 12. Formatos de Salida y Layouts

### 12.1 Formatos Disponibles

| Formato | Resolución | Uso recomendado |
|---------|------------|-----------------|
| `youtube` | 1920×1080 | YouTube principal |
| `tiktok` / `shorts` | 1080×1920 | TikTok, Reels, Shorts |
| `square` | 1080×1080 | Instagram feed, Twitter |

### 12.2 Layouts

#### Crop (default)

Recorta el video original para adaptarlo al formato de salida. Puede ser:
- **Centrado**: recorte simple al centro del frame.
- **Smart crop**: sigue la posición de tu cara usando MediaPipe (recomendado para formatos verticales).

#### Split (solo formatos verticales)

Divide la pantalla en dos secciones usando el **mismo video fuente**:

```
┌─────────────────┐
│   GAMEPLAY      │  60 % de la altura
│   (top)         │
├─────────────────┤
│  FACE CLOSE-UP  │  40 % de la altura
│  (bottom)       │
└─────────────────┘
```

- **Gameplay (arriba)**: Recorte centrado del source.
- **Cara (abajo)**: Primer plano dinámico basado en detección facial.
- Audio siempre sincronizado porque ambas secciones provienen del mismo archivo.

**Cuándo usar split:**
- Streams de gaming donde quieres mostrar tu reacción facial junto al gameplay.
- Formatos verticales donde el gameplay solo ocuparía una franja pequeña.

---

## 13. Comandos de Administración

### 13.1 Gestión de la Base de Datos

```bash
# Crear/actualizar tablas
uv run autoedit db migrate

# Resetear (⚠️ borra TODO)
uv run autoedit db reset

# Backup
uv run autoedit db backup
```

### 13.2 Listar Trabajos

```bash
# Todos los jobs
uv run autoedit job list

# Filtrar por estado
uv run autoedit job list --status failed
```

### 13.3 Ver Detalle de un Job

```bash
uv run autoedit job show <JOB_ID>
```

### 13.4 Worker en Segundo Plano

```bash
# Iniciar worker para procesar jobs encolados
make worker
```

---

## 14. Preguntas Frecuentes (FAQ)

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

Sí. Los clips son archivos MP4 estándar. Puedes abrirlos en DaVinci Resolve, Premiere, CapCut o cualquier editor. Además, el **Editor NiceGUI** te permite ajustar trim, zooms, memes, SFX y narración antes de renderizar.

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

### ¿Por qué algunos clips se omiten después del Director?

El sistema aplica **deduplicación** automática post-E7. Si dos clips cubren el mismo momento del VOD con un solapamiento mayor al 40 % (IoU ≥ 0.40), solo se conserva el de mayor confianza. Esto evita contenido repetido.

### ¿Qué diferencia hay entre el Editor (NiceGUI) y el Dashboard (Gradio)?

| Característica | Editor NiceGUI | Dashboard Gradio |
|----------------|----------------|------------------|
| Timeline interactivo | ✅ Canvas JS con drag & drop | ❌ No |
| Edición de efectos | ✅ Zooms, memes, SFX, narración | ❌ Solo re-render completo |
| Galería de clips | ✅ Con stats y acciones | ✅ Básica |
| Grid de jobs | ✅ Tarjetas visuales | ✅ Tabla simple |
| Velocidad | ✅ Más rápido (FastAPI) | ⚠️ Más lento (Gradio) |
| Recomendado para | Edición detallada | Revisión rápida |

---

## 15. Novedades v1.1

### 15.1 Editor Visual NiceGUI

La v1.1 introduce un editor web completo basado en NiceGUI:

- **Timeline interactivo** con canvas JavaScript.
- **Drag & drop** de efectos y handles de trim.
- **Panel de propiedades** dinámico según selección.
- **Persistencia** de cambios con un clic en "Guardar".
- **Re-renderizado directo** desde la interfaz.

Comando: `autoedit gui` (puerto 7880).

### 15.2 Layout Split-Screen

Nuevo modo de renderizado para formatos verticales:

- **Gameplay arriba (60 %)** + **cara abajo (40 %)**.
- Ambas secciones del **mismo video fuente** — audio siempre sincronizado.
- Sin necesidad de cámara secundaria.

Comando: `autoedit render edit --layout split --format tiktok`.

### 15.3 Deduplicación Automática

El sistema ahora evita generar clips duplicados automáticamente:

- Compara solapamiento temporal entre clips candidatos.
- Umbral: IoU ≥ 0.40.
- Conserva el clip de mayor confianza de triage.

### 15.4 Soporte Docker

Ahora puedes ejecutar todo el stack con Docker Compose:

```bash
docker compose up -d
```

Incluye: Redis, Qdrant, GUI (NiceGUI) y Worker GPU.

---

*Fin del Manual de Usuario v1.1.*
