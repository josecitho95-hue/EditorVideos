"""Register NVIDIA CUDA DLL directories on Windows for ctranslate2/faster-whisper."""

import os
import sys
from pathlib import Path


def register_nvidia_dlls() -> None:
    """Add nvidia pip package bin directories to the DLL search path.

    On Windows, packages like ``nvidia-cublas-cu12`` install their DLLs under
    ``site-packages/nvidia/<pkg>/bin``.  ``ctypes`` / ``os.add_dll_directory``
    must be told about these directories *before* any native extension tries to
    load them.
    """
    if sys.platform != "win32":
        return

    try:
        import nvidia.cublas  # type: ignore[import-untyped]
    except ImportError:
        return

    # Locate the nvidia meta-package root
    nvidia_pkg = Path(nvidia.cublas.__file__).parent.parent
    if not nvidia_pkg.name == "nvidia":
        return

    for subpkg in ("cublas", "cuda_runtime", "cudnn", "cuda_nvrtc"):
        bin_dir = nvidia_pkg / subpkg / "bin"
        if bin_dir.exists():
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                # Already added or not supported on this Python version
                pass
