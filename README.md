# AutoEdit AI

AutoEdit AI convierte VODs largos de Twitch en clips editados al estilo creator-comedy.

- **Formato principal**: YouTube (16:9, 1920×1080)
- **Formatos derivados**: Shorts de YouTube, TikTok y Reels (9:16, 1080×1920)
- **Idiomas soportados**: Español e inglés (auto-detección)

## Setup rápido

```bash
make setup
make up
uv run autoedit doctor
```

## Requisitos

- Windows 11 + WSL2 + Ubuntu 22.04
- Python 3.12+
- Docker Desktop (WSL2 backend)
- NVIDIA RTX 4070 Mobile (o similar con NVENC)
- Driver NVIDIA ≥ 555.x
- FFmpeg con NVENC

## Estructura del proyecto

Ver `docs/TECHNICAL_DESIGN.md` para la arquitectura completa.

## Licencia

Proyecto personal — no comercial.
