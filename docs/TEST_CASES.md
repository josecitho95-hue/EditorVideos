# AutoEdit AI — Documento de Casos de Prueba

**Versión:** 1.0
**Fecha:** 2026-05-10
**Relacionado con:** TECHNICAL_DESIGN.md v1.0
**Cobertura objetivo:** ≥ 85% unit / ≥ 70% pipeline principal

---

## Tabla de Contenidos

1. [Convenciones](#1-convenciones)
2. [Entorno de Pruebas](#2-entorno-de-pruebas)
3. [Módulo: Dominio (Schemas Pydantic)](#3-módulo-dominio)
4. [Módulo: Scoring (Fusión de señales)](#4-módulo-scoring)
5. [Módulo: Editorial (Triage + Director)](#5-módulo-editorial)
6. [Módulo: Render (FFmpeg commands)](#6-módulo-render)
7. [Módulo: TTS (Narration cache)](#7-módulo-tts)
8. [Módulo: Assets (RAG retrieval)](#8-módulo-assets)
9. [Módulo: LLM (OpenRouter client)](#9-módulo-llm)
10. [Módulo: Pipeline Scheduler GPU](#10-módulo-pipeline-scheduler-gpu)
11. [Integración: DB Migrations](#11-integración-db-migrations)
12. [Integración: Pipeline E0→E4 (sin LLM)](#12-integración-pipeline-e0e4)
13. [E2E: Pipeline completo (mock LLM)](#13-e2e-pipeline-completo)
14. [Matriz de cobertura por sprint](#14-matriz-de-cobertura-por-sprint)

---

## 1. Convenciones

### Identificadores

`TC-{MÓDULO}-{NNN}` — p. ej. `TC-DOM-001`, `TC-SCO-003`, `TC-INT-002`.

### Tipos

| Tipo | Descripción |
|------|-------------|
| **UNIT** | Función aislada, sin I/O real |
| **INT** | Múltiples módulos reales, DB SQLite en memoria, sin GPU |
| **E2E** | Pipeline completo con fixtures mínimas, LLM mockeado |

### Severidad

| Nivel | Descripción |
|-------|-------------|
| **P0** | Bloqueante — el sistema no puede operar si falla |
| **P1** | Crítico — funcionalidad core degradada |
| **P2** | Importante — afecta calidad o costos |
| **P3** | Menor — edge case o cosmético |

### Estado

`[ ]` Pendiente · `[x]` Implementado · `[-]` No aplica · `[!]` Bloqueado

---

## 2. Entorno de Pruebas

### Stack de testing

```
pytest 8.x
pytest-asyncio (mode=auto)
pytest-cov
respx (mock httpx)
freezegun (mock datetime)
factory-boy (opcional, generadores de entidades)
```

### Fixtures globales (conftest.py)

| Fixture | Scope | Descripción |
|---------|-------|-------------|
| `db_session` | function | SQLite in-memory, todas las tablas |
| `redis_client` | session | Redis en Docker (o fakeredis) |
| `qdrant_client` | session | Qdrant in-memory |
| `mock_openrouter` | function | respx route que simula OpenRouter |
| `sample_vod` | session | Fila `vods` con VOD sintético 30s |
| `sample_job` | function | `Job` en estado `queued` |
| `sample_highlights` | function | 3 `Highlight` con intents distintos |
| `sample_assets` | session | 5 memes + 5 SFX con embeddings falsos |
| `voice_ref_wav` | session | 35s wav sintético 24kHz |
| `short_vod_mp4` | session | MP4 sintético 30s con pico de audio en t=15s |

### Variables de entorno para tests

```
OPENROUTER_API_KEY=test-key
DATA_DIR=./tests/tmp
REDIS_URL=redis://localhost:6379/1
QDRANT_URL=http://localhost:6333
LANGFUSE_PUBLIC_KEY=  # vacío para deshabilitar en tests
```

---

## 3. Módulo: Dominio

> Archivo de test: `tests/unit/domain/`

---

### TC-DOM-001 — JobConfig valida rango de target_clip_count
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 0
- **Descripción:** `target_clip_count` debe ser entero en [1, 30]. Valores fuera de rango deben lanzar `ValidationError`.
- **Precondiciones:** ninguna
- **Pasos:**
  1. Crear `JobConfig(target_clip_count=10)` → debe construirse OK.
  2. Crear `JobConfig(target_clip_count=0)` → debe lanzar `ValidationError`.
  3. Crear `JobConfig(target_clip_count=31)` → debe lanzar `ValidationError`.
- **Resultado esperado:** OK / ValidationError / ValidationError respectivamente.

---

### TC-DOM-002 — JobConfig defaults razonables
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 0
- **Descripción:** `JobConfig()` sin argumentos debe construirse con los defaults documentados.
- **Pasos:**
  1. `cfg = JobConfig()`
  2. Verificar: `clip_max_duration_sec == 60.0`, `output_resolution == (1080, 1920)`, `director_model == "deepseek/deepseek-chat-v3"`, `language == "es"`.
- **Resultado esperado:** todos los campos coinciden con los defaults del TDD §7.2.

---

### TC-DOM-003 — EditDecision serializa y deserializa sin pérdida
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 1
- **Descripción:** `EditDecision` debe round-trip vía `model_dump_json()` / `model_validate_json()` sin pérdida de información.
- **Pasos:**
  1. Construir `EditDecision` completo con 2 zooms, 2 memes, 1 SFX, 1 narración.
  2. Serializar a JSON string.
  3. Deserializar a nueva instancia.
  4. Comparar campo a campo.
- **Resultado esperado:** instancias iguales; tipos numéricos mantienen precisión.

---

### TC-DOM-004 — ZoomEvent rechaza intensity fuera de rango
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 1
- **Descripción:** `ZoomEvent.intensity` debe estar en [1.0, 2.5].
- **Pasos:**
  1. `ZoomEvent(intensity=0.9, ...)` → `ValidationError`.
  2. `ZoomEvent(intensity=2.6, ...)` → `ValidationError`.
  3. `ZoomEvent(intensity=1.8, ...)` → OK.
- **Resultado esperado:** errores en casos límite, éxito en valor válido.

---

### TC-DOM-005 — MemeOverlay limita max_length en lista de EditDecision
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 1
- **Descripción:** `EditDecision.meme_overlays` tiene `max_length=8`. Insertar 9 debe fallar.
- **Pasos:**
  1. Crear lista de 9 `MemeOverlay` válidos.
  2. Asignar al campo `meme_overlays` de `EditDecision`.
- **Resultado esperado:** `ValidationError` indicando `max_length`.

---

### TC-DOM-006 — NarrationCue limita texto a 300 caracteres
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 3
- **Pasos:**
  1. `NarrationCue(text="A" * 301, ...)` → `ValidationError`.
  2. `NarrationCue(text="A" * 300, ...)` → OK.

---

### TC-DOM-007 — WindowCandidate score está normalizado
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 1
- **Descripción:** El campo `score` de `WindowCandidate` debe ser float ∈ [0.0, 1.0].
- **Pasos:**
  1. `WindowCandidate(score=1.01, ...)` → `ValidationError`.
  2. `WindowCandidate(score=-0.01, ...)` → `ValidationError`.
  3. `WindowCandidate(score=0.85, ...)` → OK.

---

### TC-DOM-008 — SubtitleStyle defaults documentados
- **Tipo:** UNIT | **Severidad:** P3 | **Sprint:** 2
- **Pasos:**
  1. `s = SubtitleStyle()`
  2. Verificar `font_family == "Arial Black"`, `primary_color == "#FFFFFF"`, `karaoke_highlight_color == "#FFD700"`.

---

## 4. Módulo: Scoring

> Archivo de test: `tests/unit/scoring/`

---

### TC-SCO-001 — fuse_signals normaliza todas las señales a [0, 1]
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 1
- **Descripción:** Dado un DataFrame con señales brutas de cualquier magnitud, `fuse_signals()` debe devolver una Serie con valores en [0.0, 1.0].
- **Precondiciones:** DataFrame de 100 filas con ruido gaussiano en 4 columnas.
- **Pasos:**
  1. Generar DataFrame con `np.random.randn(100, 4)`.
  2. Llamar `fuse_signals(df, weights={"audio":0.35,"chat":0.30,"transcript":0.20,"scene":0.15})`.
  3. Verificar `result.min() >= 0.0` y `result.max() <= 1.0`.
- **Resultado esperado:** Serie de floats normalizados.

---

### TC-SCO-002 — pico claro en audio se refleja en score alto
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 1
- **Descripción:** Un VOD sintético con un pico de audio en t=15s debe producir un window centrado cerca de ese instante con score > 0.7.
- **Pasos:**
  1. Crear DataFrame de 30 filas (30s) con `audio_rms_db` = -40 dB base, -5 dB en t=15.
  2. Llamar `fuse_signals()` + `extract_windows(top_n=3)`.
  3. Verificar que la window de mayor score incluye t=15s.
  4. Verificar que su score > 0.7.
- **Resultado esperado:** window con start_sec ≤ 15 ≤ end_sec, score > 0.7.

---

### TC-SCO-003 — NMS temporal elimina windows solapadas
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 1
- **Descripción:** Dos peaks artificiales a t=10 y t=12 (overlap > 30%) deben producir solo 1 window en el output, la de mayor score.
- **Pasos:**
  1. Crear scores artificiales con picos en t=10 y t=12 (ambos > 0.8).
  2. Llamar `extract_windows(top_n=5, overlap_threshold=0.3)`.
  3. Verificar que las dos windows no coexisten en el resultado.
- **Resultado esperado:** solo la window con mayor score es retenida.

---

### TC-SCO-004 — chat keyword spike amplifica score
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 1
- **Descripción:** Cuando `chat_kw_score` es 1.0 en un segundo, ese segundo debe tener contribución de chat ≥ 0.25 (su peso × 1.0).
- **Pasos:**
  1. DataFrame de 10s con todas las señales en 0 salvo `chat_kw_score=1.0` en t=5.
  2. `fuse_signals(weights={"audio":0.35,"chat":0.30,"transcript":0.20,"scene":0.15})`.
  3. Verificar `result[5] ≥ 0.25`.

---

### TC-SCO-005 — extract_windows respeta clip_min_duration
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 1
- **Descripción:** Ninguna window en el resultado puede tener duración < `clip_min_duration_sec`.
- **Pasos:**
  1. `extract_windows(top_n=10, clip_min_duration_sec=15.0)`.
  2. Para cada window: `assert window.end_sec - window.start_sec >= 15.0`.

---

### TC-SCO-006 — sin señal → scores uniformes bajos
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 1
- **Descripción:** DataFrame con todas las señales constantes (sin varianza) debe producir scores uniformes, no dividir por cero.
- **Pasos:**
  1. DataFrame con todos los valores = 0.
  2. `fuse_signals(df, ...)` no debe lanzar excepción.
  3. Todos los scores deben ser ≤ 0.5.

---

### TC-SCO-007 — rank es consecutivo y sin gaps
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 1
- **Pasos:**
  1. `windows = extract_windows(top_n=5, ...)`.
  2. Verificar `[w.rank for w in windows] == [1, 2, 3, 4, 5]`.

---

## 5. Módulo: Editorial

> Archivo de test: `tests/unit/editorial/`

---

### TC-EDI-001 — build_director_prompt incluye JSON Schema completo
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 5
- **Descripción:** El prompt enviado al Director debe incluir el JSON Schema de `EditDecision` para guiar la respuesta.
- **Pasos:**
  1. Llamar `build_director_prompt(highlight, transcript, memes, sfx)`.
  2. Verificar que `"EditDecision"` o `"highlight_id"` aparecen en el string del prompt.
  3. Verificar que `"zoom_events"` y `"narration_cues"` aparecen.
- **Resultado esperado:** prompt string contiene el schema embebido.

---

### TC-EDI-002 — parseo de EditDecision desde respuesta LLM válida
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 5
- **Descripción:** Un JSON string válido de OpenRouter debe parsearse a `EditDecision` sin errores.
- **Pasos:**
  1. Preparar JSON string que representa un `EditDecision` completo y válido.
  2. `ed = EditDecision.model_validate_json(json_str)`.
  3. Verificar `ed.highlight_id` es el esperado.
- **Resultado esperado:** `EditDecision` instanciado correctamente.

---

### TC-EDI-003 — respuesta LLM con JSON malformado lanza error manejable
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 5
- **Descripción:** El Director debe capturar `ValidationError`/`JSONDecodeError` del LLM y convertirlo en un error recuperable (no crash del worker).
- **Pasos:**
  1. Mockear OpenRouter para devolver `{"intent": "fail"}` (incompleto).
  2. Invocar `director.run(...)`.
  3. Verificar que se lanza `EditDecisionParseError` con mensaje descriptivo.
- **Resultado esperado:** excepción controlada, no `RuntimeError`.

---

### TC-EDI-004 — build_triage_prompt incluye transcripción y frames
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 5
- **Descripción:** El prompt de triage debe incluir la transcripción y referencias a los 4 frames.
- **Pasos:**
  1. `prompt, images = build_triage_prompt(window, transcript_excerpt, chat_samples, frames)`.
  2. Verificar que `transcript_excerpt` aparece en `prompt`.
  3. Verificar que `images` tiene exactamente 4 elementos.

---

### TC-EDI-005 — TriageResult con keep=False descarta window
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 5
- **Descripción:** Si `TriageResult.keep == False`, el `Highlight` resultante debe tener `discarded=True`.
- **Pasos:**
  1. `triage_result = TriageResult(intent="fail", confidence=0.3, keep=False, reasoning="boring")`.
  2. `highlight = apply_triage(window, triage_result)`.
  3. `assert highlight.discarded == True`.

---

### TC-EDI-006 — narration text respeta límite de 300 chars en director
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 5
- **Descripción:** Si el Director produce un `NarrationCue` con texto > 300 chars, debe detectarse y rechazarse antes de TTS.
- **Pasos:**
  1. Construir `EditDecision` con `NarrationCue(text="A" * 301)`.
  2. Llamar `validate_edit_decision(ed)`.
  3. Verificar que falla con error específico.

---

## 6. Módulo: Render

> Archivo de test: `tests/unit/render/`

---

### TC-REN-001 — comando trim usa parámetros de Trim correctamente
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 2
- **Descripción:** `compositor.build_render_command()` con `trim=(100.0, 140.0)` debe generar argumentos FFmpeg con `-ss 100.0 -to 140.0`.
- **Pasos:**
  1. Crear `EditDecision` mínimo con `trim=Trim(start_sec=100.0, end_sec=140.0)`.
  2. `cmd = build_render_command(source, edit, ...)`.
  3. Verificar `"-ss"` y `"100.0"` y `"-to"` y `"140.0"` en `cmd`.
- **Resultado esperado:** argumentos correctos.

---

### TC-REN-002 — overlay meme genera filter enable con ventana temporal
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 2
- **Descripción:** Un `MemeOverlay(at_sec=5.0, duration_sec=2.0)` debe producir `enable='between(t,5.0,7.0)'` en el filter_complex.
- **Pasos:**
  1. `EditDecision` con un `MemeOverlay(at_sec=5.0, duration_sec=2.0)`.
  2. `fc = build_filter_complex(edit, ...)`.
  3. Verificar `"between(t,5.0,7.0)"` en la string del filter.

---

### TC-REN-003 — SFX cue genera adelay correcto
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 2
- **Descripción:** `SfxCue(at_sec=3.0)` debe producir `adelay=3000|3000` en el audio filter.
- **Pasos:**
  1. `EditDecision` con `SfxCue(at_sec=3.0, ...)`.
  2. `audio_fc = build_audio_filter(edit, ...)`.
  3. Verificar `"adelay=3000|3000"` en la string.

---

### TC-REN-004 — crop 9:16 usa resolución de destino correcta
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 2
- **Descripción:** Para input 1920×1080, el crop debe ser `608×1080` (1080 * 9/16 ≈ 608, ajustado a par).
- **Pasos:**
  1. `crop = compute_center_crop(input_w=1920, input_h=1080, target_aspect=9/16)`.
  2. Verificar `crop.w == 608` y `crop.h == 1080`.
  3. Verificar que `crop.x == (1920 - 608) // 2 == 656`.

---

### TC-REN-005 — NVENC preset se aplica al comando
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 2
- **Descripción:** `RenderConfig(output_codec="h264_nvenc", nvenc_preset="p4")` debe producir `-c:v h264_nvenc -preset p4` en el comando final.
- **Pasos:**
  1. `cmd = build_render_command(source, edit, config=RenderConfig(output_codec="h264_nvenc", nvenc_preset="p4"), ...)`.
  2. Verificar `"-c:v"`, `"h264_nvenc"`, `"-preset"`, `"p4"` en `cmd`.

---

### TC-REN-006 — zoom punch-in genera zoompan filter
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 6
- **Descripción:** `ZoomEvent(kind=ZoomKind.PUNCH_IN, at_sec=2.0, duration_sec=0.5, intensity=1.8)` debe producir filtro `zoompan`.
- **Pasos:**
  1. `fc = build_filter_complex(edit_with_zoom, ...)`.
  2. Verificar `"zoompan"` en el filter.

---

### TC-REN-007 — ducking: audio original baja durante narración
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 3
- **Descripción:** `NarrationCue(at_sec=5.0, duck_main_audio_db=-10.0)` debe generar `volume=0.316:enable='between(t,5.0,...)'` (≈ -10 dB = 10^(-10/20) ≈ 0.316).
- **Pasos:**
  1. `audio_fc = build_audio_filter(edit_with_narration, narration_durations={...})`.
  2. Verificar que la string contiene `volume` con valor ≈ 0.316 y el rango temporal correcto.

---

### TC-REN-008 — salida incluye movflags faststart
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 2
- **Descripción:** El moov atom debe ir al inicio del archivo para streaming. Siempre incluir `-movflags +faststart`.
- **Pasos:**
  1. Cualquier llamada a `build_render_command(...)`.
  2. Verificar `"-movflags"` y `"+faststart"` en la lista.

---

### TC-REN-009 — subs ASS contiene marcadores karaoke
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 2
- **Descripción:** `build_ass_subtitles()` con 3 palabras debe generar 1 evento ASS con `\k` por palabra.
- **Pasos:**
  1. `words = [Word("Hola", 0.0, 0.4), Word("que", 0.4, 0.6), Word("tal", 0.6, 1.0)]`.
  2. `ass = build_ass_subtitles(words, style=SubtitleStyle())`.
  3. Contar ocurrencias de `\\k` en la sección `[Events]` → debe ser 3.

---

## 7. Módulo: TTS

> Archivo de test: `tests/unit/tts/`

---

### TC-TTS-001 — cache hit devuelve Narration existente sin re-generar
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 3
- **Descripción:** Segunda llamada con mismo texto + voice_id debe devolver la narración cacheada sin llamar al engine.
- **Pasos:**
  1. `cache = NarrationCache(db_session, data_dir)`.
  2. `n1 = await cache.get_or_generate("hola mundo", "me_v1", engine=mock_engine)`.
  3. `n2 = await cache.get_or_generate("hola mundo", "me_v1", engine=mock_engine)`.
  4. Verificar `mock_engine.generate.call_count == 1` (solo una llamada al engine).
  5. Verificar `n1.id == n2.id`.
- **Resultado esperado:** solo 1 llamada al engine de TTS.

---

### TC-TTS-002 — compute_key es determinista
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 3
- **Descripción:** Mismos inputs → mismo key. Keys distintos para inputs distintos.
- **Pasos:**
  1. `k1 = NarrationCache.compute_key("hola", "me_v1")`.
  2. `k2 = NarrationCache.compute_key("hola", "me_v1")`.
  3. `k3 = NarrationCache.compute_key("adios", "me_v1")`.
  4. Verificar `k1 == k2` y `k1 != k3`.

---

### TC-TTS-003 — cache miss con texto nuevo llama al engine
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 3
- **Pasos:**
  1. `cache.get_or_generate("texto nuevo", "me_v1", engine=mock_engine)`.
  2. Verificar `mock_engine.generate.call_count == 1`.

---

### TC-TTS-004 — narración cacheada persiste en SQLite
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 3
- **Descripción:** La narración generada debe quedar registrada en la tabla `narrations`.
- **Pasos:**
  1. Generar narración.
  2. `row = db.exec(select(Narration).where(Narration.text == "hola mundo")).first()`.
  3. Verificar `row is not None` y `row.voice_id == "me_v1"`.

---

### TC-TTS-005 — audio_path debe existir en disco tras generar
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 3
- **Pasos:**
  1. Generar narración (engine mock escribe silencio WAV real).
  2. `assert Path(narration.audio_path).exists()`.

---

### TC-TTS-006 — incrementa used_count en cada acceso
- **Tipo:** UNIT | **Severidad:** P3 | **Sprint:** 3
- **Pasos:**
  1. Generar narración (used_count=0).
  2. Acceder 3 veces a la misma narración.
  3. Verificar `narration.used_count == 3`.

---

## 8. Módulo: Assets (RAG)

> Archivo de test: `tests/unit/assets/`

---

### TC-AST-001 — búsqueda retorna assets con intent_affinity matching
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 4
- **Descripción:** Búsqueda de assets para intent `fail` solo debe devolver assets cuyo `intent_affinity` incluye `"fail"`.
- **Precondiciones:** Qdrant con 10 assets: 5 con `intent_affinity=["fail"]`, 5 con `["win"]`.
- **Pasos:**
  1. `results = await asset_retrieval.search_visual("funny fail", intent=Intent.FAIL, k=10)`.
  2. Verificar que todos los resultados tienen `Intent.FAIL` en `intent_affinity`.
  3. Verificar `len(results) <= 5`.

---

### TC-AST-002 — deduplicación excluye assets usados recientemente
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 4
- **Descripción:** Si un asset fue usado en las últimas 48 h, no debe aparecer en resultados.
- **Pasos:**
  1. Registrar en `asset_usages` el asset `A1` hace 24 h.
  2. Buscar assets; `A1` debe estar excluido aunque su similitud sea máxima.
- **Resultado esperado:** `A1` ausente de resultados.

---

### TC-AST-003 — búsqueda de SFX usa embeddings CLAP
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 4
- **Descripción:** La búsqueda de audio SFX debe usar el campo `assets_audio` de Qdrant, no el visual.
- **Pasos:**
  1. `await asset_retrieval.search_audio("dramatic fail sound", intent=Intent.FAIL, k=3)`.
  2. Verificar que la llamada a Qdrant usa `collection_name="assets_audio"`.

---

### TC-AST-004 — agregar asset sin archivo válido falla
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 4
- **Pasos:**
  1. `await catalog.add_asset(file_path=Path("/no/existe.png"), kind=AssetKind.VISUAL_IMAGE, ...)`.
  2. Verificar `AssetNotFoundError` o `FileNotFoundError`.

---

### TC-AST-005 — sha256 se calcula correctamente al indexar
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 4
- **Pasos:**
  1. Añadir asset con contenido conocido.
  2. Calcular sha256 manualmente del mismo archivo.
  3. Verificar que `asset.sha256 == sha256_manual`.

---

## 9. Módulo: LLM (OpenRouter)

> Archivo de test: `tests/unit/llm/`

---

### TC-LLM-001 — pricing.estimate devuelve USD no negativos
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 0
- **Pasos:**
  1. `usd = pricing.estimate("deepseek/deepseek-chat-v3", tokens_in=1000, tokens_out=500)`.
  2. Verificar `usd > 0` y `usd < 0.01` (para esos tokens).

---

### TC-LLM-002 — modelo desconocido lanza UnknownModelError
- **Tipo:** UNIT | **Severidad:** P2 | **Sprint:** 0
- **Pasos:**
  1. `pricing.estimate("modelo/inexistente", 100, 50)` → `UnknownModelError`.

---

### TC-LLM-003 — retry en error 429 con backoff exponencial
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 0
- **Descripción:** Cuando OpenRouter devuelve 429, el cliente debe reintentar con backoff.
- **Precondiciones:** mock httpx: primeras 2 llamadas → 429; tercera → 200 OK.
- **Pasos:**
  1. Configurar mock con respx.
  2. `await openrouter_client.chat(messages=[...])`.
  3. Verificar que se realizaron 3 llamadas HTTP.
  4. Verificar que el resultado es la respuesta 200.
  5. Verificar que entre llamadas hubo delays de 1s y 2s (freezegun).

---

### TC-LLM-004 — error 400 no se reintenta
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 0
- **Pasos:**
  1. Mock OpenRouter: siempre 400.
  2. `await openrouter_client.chat(...)` → debe lanzar `LLMBadRequestError` sin reintentos.
  3. Verificar 1 sola llamada HTTP.

---

### TC-LLM-005 — circuit breaker pausa tras N fallos consecutivos
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 0
- **Pasos:**
  1. Configurar umbral circuit breaker = 3 fallos.
  2. Hacer 3 llamadas que fallan con 503.
  3. Verificar que la 4ta llamada lanza `CircuitOpenError` sin hacer HTTP request.

---

### TC-LLM-006 — cost_entry se registra en DB después de cada llamada
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 0
- **Pasos:**
  1. Mock OpenRouter devuelve `usage={prompt_tokens:100, completion_tokens:50}`.
  2. Llamar `tracked_call(job_id=job.id, stage="E7_direct", ...)`.
  3. `entries = db.exec(select(CostEntry).where(...))`.
  4. Verificar que hay 1 entry con `tokens_in=100`, `tokens_out=50`, `usd > 0`.

---

## 10. Módulo: Pipeline Scheduler GPU

> Archivo de test: `tests/unit/pipeline/`

---

### TC-GPU-001 — mutex impide dos etapas GPU simultáneas
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 1
- **Descripción:** Dos co-routines que solicitan el compute lock no deben ejecutarse en paralelo.
- **Pasos:**
  1. Crear `GpuScheduler(max_vram_mb=7000)`.
  2. Lanzar 2 tasks async que adquieren el lock y duran 50 ms cada una.
  3. Medir tiempo total: debe ser ≥ 100 ms (secuencial) y < 150 ms.
- **Resultado esperado:** ejecución secuencial garantizada.

---

### TC-GPU-002 — eviction de modelo cuando VRAM insuficiente
- **Tipo:** UNIT | **Severidad:** P0 | **Sprint:** 1
- **Descripción:** Si cargar el nuevo modelo excede el budget, el LRU debe ser descargado primero.
- **Pasos:**
  1. Scheduler con budget = 5000 MB.
  2. Cargar `whisper` (3000 MB), luego `clip` (1500 MB). Total = 4500 MB. OK.
  3. Solicitar `f5_tts` (4000 MB). Total con todos = 8500 → excede.
  4. Verificar que el modelo LRU (`whisper`) fue descargado.
  5. Verificar que `f5_tts` está cargado.
  6. Total VRAM = 1500 + 4000 = 5500 MB → excede aún. Verificar que también se descargó `clip`.
- **Resultado esperado:** solo `f5_tts` cargado.

---

### TC-GPU-003 — NVENC no compite con compute lock
- **Tipo:** UNIT | **Severidad:** P1 | **Sprint:** 2
- **Descripción:** El render NVENC (que usa bloque dedicado) puede correr mientras compute lock está libre.
- **Pasos:**
  1. Verificar que `render_with_nvenc()` no intenta adquirir el compute lock.
  2. El render puede ser invocado con el scheduler en modo "idle" (sin lock activo).

---

## 11. Integración: DB Migrations

> Archivo de test: `tests/integration/test_db_migrations.py`

---

### TC-INT-001 — migración crea todas las tablas esperadas
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 0
- **Pasos:**
  1. `run_migrations(engine=in_memory_engine)`.
  2. Consultar `sqlite_master` para listar tablas.
  3. Verificar existencia de: jobs, vods, run_steps, transcript_segments, transcript_words, chat_messages, windows, highlights, edit_decisions, clips, assets, asset_usages, narrations, cost_entries.
- **Resultado esperado:** 14 tablas creadas.

---

### TC-INT-002 — migración es idempotente
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 0
- **Pasos:**
  1. Correr `run_migrations()` dos veces seguidas.
  2. Verificar que no lanza error y las tablas están correctas.

---

### TC-INT-003 — índices creados correctamente
- **Tipo:** INT | **Severidad:** P1 | **Sprint:** 0
- **Pasos:**
  1. `run_migrations()`.
  2. Consultar `sqlite_master WHERE type='index'`.
  3. Verificar existencia de: `idx_jobs_status`, `idx_transcript_vod_time`, `idx_chat_vod_time`, `idx_windows_job_rank`, `idx_highlights_job`, `idx_clips_job`.

---

### TC-INT-004 — FK constraint activa (cascade delete)
- **Tipo:** INT | **Severidad:** P1 | **Sprint:** 0
- **Descripción:** Borrar un job debe borrar en cascade sus windows y highlights.
- **Pasos:**
  1. Insertar job, 3 windows, 3 highlights.
  2. `db.delete(job)`.
  3. Verificar `windows count == 0` y `highlights count == 0`.

---

### TC-INT-005 — WAL mode habilitado
- **Tipo:** INT | **Severidad:** P2 | **Sprint:** 0
- **Pasos:**
  1. `result = db.exec(text("PRAGMA journal_mode")).first()`.
  2. Verificar `result[0] == "wal"`.

---

## 12. Integración: Pipeline E0→E4 (sin LLM)

> Archivo de test: `tests/integration/test_pipeline_stages.py`

---

### TC-INT-010 — E0 ingest persiste VOD en DB y disco
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 1
- **Precondiciones:** `yt-dlp` mockeado para devolver `short_vod.mp4`; `chat-downloader` mockeado.
- **Pasos:**
  1. `await run_stage_ingest(job, vod_url="mock://twitch/vod/123")`.
  2. Verificar que `data/vods/123/source.mp4` existe.
  3. Verificar que `data/vods/123/chat.jsonl` existe.
  4. Verificar fila en tabla `vods` con `id="123"`.
  5. Verificar `run_steps` tiene E0 con `status="done"`.
- **Resultado esperado:** archivos en disco + registros DB.

---

### TC-INT-011 — E1 extract produce audio.wav y scenes.json
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 1
- **Pasos:**
  1. Dado `short_vod.mp4` (fixture 30s), correr E1.
  2. Verificar `audio.wav` existe, sample rate = 16000, canales = 1.
  3. Verificar `scenes.json` existe y es JSON válido con al menos 1 escena.

---

### TC-INT-012 — E2 transcribe produce transcript.json con words
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 1
- **Precondiciones:** faster-whisper cargado (o mock si en CI sin GPU).
- **Pasos:**
  1. Correr E2 sobre `short_vod.mp4` que tiene audio sintético con voz.
  2. Verificar `transcript.json` existe.
  3. Verificar que hay al menos 1 segmento con `words` no vacío.
  4. Verificar que filas en `transcript_segments` y `transcript_words` fueron insertadas.

---

### TC-INT-013 — E3 analyze produce signals.parquet con todas las columnas
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 1
- **Pasos:**
  1. Dado audio.wav + chat.jsonl + transcript.json + scenes.json.
  2. Correr E3.
  3. `df = pd.read_parquet("signals.parquet")`.
  4. Verificar que `df` tiene columnas: t_sec, audio_rms_db, audio_loudness_lufs, chat_msg_per_sec, chat_unique_users, chat_kw_score, transcript_kw_score, is_scene_cut.
  5. Verificar `len(df) == int(vod_duration_sec)`.

---

### TC-INT-014 — E4 score devuelve top-N ventanas ordenadas por score
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 1
- **Pasos:**
  1. Dado signals.parquet con pico claro en t=15s.
  2. Correr E4 con `top_n=5`.
  3. `windows = db.exec(select(Window).where(...).order_by(Window.rank))`.
  4. Verificar `len(windows) <= 5`.
  5. Verificar `windows[0].score >= windows[1].score` (orden descendente).
  6. Verificar que la window top incluye t=15s.

---

### TC-INT-015 — idempotencia: re-correr etapa ya hecha usa caché
- **Tipo:** INT | **Severidad:** P1 | **Sprint:** 1
- **Pasos:**
  1. Correr E1 completo.
  2. Correr E1 de nuevo.
  3. Verificar que el `run_step` de la segunda corrida tiene `status="cached"`.
  4. Verificar que el tiempo de la segunda corrida es < 500 ms (no reprocesa).

---

### TC-INT-016 — pipeline E0→E4 completo con short_vod
- **Tipo:** INT | **Severidad:** P0 | **Sprint:** 1
- **Descripción:** Test de humo del pipeline completo hasta scoring.
- **Pasos:**
  1. `await pipeline.run(job, stages=[E0, E1, E2, E3, E4])`.
  2. Verificar `job.status == "done"` (para esas etapas).
  3. Verificar al menos 1 window en DB.
  4. Sin excepción lanzada.

---

## 13. E2E: Pipeline completo (mock LLM)

> Archivo de test: `tests/integration/test_e2e_pipeline.py`

---

### TC-E2E-001 — job completo produce clips MP4 en disco
- **Tipo:** E2E | **Severidad:** P0 | **Sprint:** 5
- **Precondiciones:** LLM mockeado con respx; F5-TTS mock produce silencio WAV; short_vod.mp4 disponible.
- **Pasos:**
  1. Encolar job con `short_vod.mp4`.
  2. Correr worker hasta completion.
  3. Verificar `job.status == "done"`.
  4. Verificar que existen ≥ 1 clip en `data/vods/xxx/clips/`.
  5. Verificar que cada clip tiene resolución 1080×1920 (consultar con `ffprobe`).
  6. Verificar que filas en `clips` apuntan a archivos existentes.
- **Resultado esperado:** pipeline completo, clips válidos.

---

### TC-E2E-002 — clip tiene subtítulos quemados
- **Tipo:** E2E | **Severidad:** P1 | **Sprint:** 2
- **Pasos:**
  1. Generar clip con subtítulos.
  2. Verificar con ffprobe que el stream de video tiene burn-in (no sidecar).
  3. Verificar que el archivo `.ass` fue generado en disco.

---

### TC-E2E-003 — costo total registrado correctamente
- **Tipo:** E2E | **Severidad:** P1 | **Sprint:** 5
- **Pasos:**
  1. Correr pipeline completo con mock LLM que devuelve `usage={prompt_tokens:500, completion_tokens:200}`.
  2. `total = db.exec(select(func.sum(CostEntry.usd)).where(CostEntry.job_id==job.id)).scalar()`.
  3. Verificar `job.total_cost_usd == total` y `total > 0`.

---

### TC-E2E-004 — fallo en E7 (director) pone job en failed con traceback
- **Tipo:** E2E | **Severidad:** P0 | **Sprint:** 5
- **Pasos:**
  1. Mockear OpenRouter para E7 que lanza `httpx.TimeoutException` siempre (más allá de retries).
  2. Correr pipeline.
  3. Verificar `job.status == "failed"`.
  4. Verificar `job.error` contiene traceback descriptivo.
  5. Verificar que el job se puede reintentar desde `--from-stage E7`.

---

### TC-E2E-005 — VOD source borrado tras job done si configurado
- **Tipo:** E2E | **Severidad:** P2 | **Sprint:** 1
- **Pasos:**
  1. `config.delete_source_after = True`.
  2. Correr pipeline completo.
  3. Verificar `not Path("data/vods/xxx/source.mp4").exists()`.
  4. Verificar `vod.deleted_source == 1`.

---

### TC-E2E-006 — rerun parcial desde E5 no reprocesa E0-E4
- **Tipo:** E2E | **Severidad:** P1 | **Sprint:** 1
- **Pasos:**
  1. Correr pipeline hasta E4.
  2. Simular fallo en E5.
  3. Reanudar desde `--from-stage E5`.
  4. Verificar que E0-E4 tienen `status="cached"` en el segundo run.
  5. Verificar que E5 se ejecutó de nuevo.

---

## 14. Matriz de cobertura por sprint

| Sprint | TCs nuevos | TCs automatizables | Cobertura unit objetivo |
|--------|------------|-------------------|------------------------|
| 0 | DOM-001,002 · LLM-001..006 · INT-001..005 | 15 | ≥60% |
| 1 | SCO-001..007 · INT-010..016 · GPU-001..003 | 20 | ≥70% |
| 2 | REN-001..009 | 9 | ≥75% |
| 3 | TTS-001..006 | 6 | ≥78% |
| 4 | AST-001..005 | 5 | ≥80% |
| 5 | EDI-001..006 · E2E-001,003,004 | 8 | ≥85% |
| 6 | REN-006 (zoom) + tests de reframe | 4 | ≥85% |
| 7 | Dashboard UI tests (Gradio playwright) | variable | ≥85% |
| 8 | Eval set (cualitativos) | — | — |

---

*Fin del documento de casos de prueba.*
