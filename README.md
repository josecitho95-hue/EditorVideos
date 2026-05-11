# AutoEdit AI

AutoEdit AI convierte VODs largos de Twitch en clips editados al estilo creator-comedy.

- **Formato principal**: YouTube (16:9, 1920×1080)
- **Formatos derivados**: Shorts de YouTube, TikTok y Reels (9:16, 1080×1920)
- **Layout split-screen**: Gameplay arriba (60 %) + cara en primer plano abajo (40 %) para formato vertical
- **Idiomas soportados**: Español e inglés (auto-detección)
- **Interfaces**: CLI (Typer), Dashboard web (Gradio) y Editor visual (NiceGUI)

## Setup rápido (local)

```bash
make setup
make up
uv run autoedit doctor
```

## Setup rápido (Docker)

```bash
cp .env.example .env          # editar OPENROUTER_API_KEY
docker compose --profile setup run --rm init-db
docker compose --profile setup run --rm download-models
docker compose up -d
open http://localhost:7880    # NiceGUI editor
```

## Requisitos

- Windows 11 + WSL2 + Ubuntu 22.04 (local) o Linux con NVIDIA Container Toolkit (Docker)
- Python 3.12+
- Docker Desktop (WSL2 backend) — opcional pero recomendado
- NVIDIA RTX 4070 Mobile (o similar con NVENC)
- Driver NVIDIA ≥ 555.x
- FFmpeg con NVENC

## Interfaces disponibles

| Interfaz | Comando | Puerto | Descripción |
|----------|---------|--------|-------------|
| **CLI** | `autoedit` | — | Comandos completos para automatización |
| **Dashboard** | `autoedit dashboard` | 7860 | Gradio — revisión rápida de clips |
| **Editor** | `autoedit gui` | 7880 | NiceGUI — timeline interactivo, edición visual |

## Estructura del proyecto

Ver `docs/TECHNICAL_DESIGN.md` para la arquitectura completa.  
Ver `docs/MANUAL_TECNICO.md`, `docs/MANUAL_IMPLEMENTACION.md` y `docs/MANUAL_USUARIO.md` para documentación detallada.

## Licencia

Proyecto personal — no comercial.
