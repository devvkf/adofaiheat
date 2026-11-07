"""Identify a song from an audio/video file via Shazam.

Works from any directory and with any `python` on PATH: if shazamio isn't
importable it re-executes itself under an interpreter that has it.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MEDIA = SCRIPT_DIR / "3932365722030918418.ogg"
FFMPEG_CANDIDATES = ("python313", "python3.13", "python3")


def _ensure_shazamio() -> None:
    try:
        import shazamio  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get("RECOGNISE_REEXEC"):
        sys.exit("shazamio is not installed in this interpreter.")

    # The default `python` may be a project venv without shazamio; look for one
    # that has it and hand over, preserving arguments.
    for cand in FFMPEG_CANDIDATES:
        exe = shutil.which(cand)
        if not exe:
            continue
        probe = subprocess.run(
            [exe, "-c", "import shazamio"], capture_output=True
        )
        if probe.returncode == 0:
            os.environ["RECOGNISE_REEXEC"] = "1"
            os.execv(exe, [exe, str(Path(__file__).resolve()), *sys.argv[1:]])

    sys.exit(
        "No interpreter with shazamio found. Try: python313 -m pip install shazamio"
    )


_ensure_shazamio()

from shazamio import Serialize, Shazam  # noqa: E402


def to_wav(src: Path) -> tuple[Path, Path]:
    """Transcode to mono 44.1kHz PCM.

    shazamio's Rust decoder (symphonia) can't decode HE-AAC — it raises
    SignatureError: "unsupported feature: aac: aac too complex". ffmpeg can.
    Returns the wav path and the temp dir to clean up.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="shazam_"))
    out = tmpdir / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "44100", str(out)],
        check=True,
    )
    return out, tmpdir


async def recognize(path: Path) -> dict:
    async with Shazam() as shazam:
        try:
            return await shazam.recognize(str(path))
        except Exception:
            if shutil.which("ffmpeg") is None:
                raise
            wav, tmpdir = to_wav(path)
            try:
                return await shazam.recognize(str(wav))
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)


def resolve_media(arg: str | None) -> Path:
    """Accept an absolute path, a cwd-relative path, or a bare filename
    that lives next to this script."""
    if arg is None:
        path = DEFAULT_MEDIA
    else:
        path = Path(arg).expanduser()
        if not path.is_absolute() and not path.exists():
            path = SCRIPT_DIR / path
    path = path.resolve()
    if not path.exists():
        sys.exit(f"No such file: {path}")
    return path


async def main() -> None:
    media = resolve_media(sys.argv[1] if len(sys.argv) > 1 else None)
    out = await recognize(media)

    if not out.get("matches"):
        print(f"No match: {media.name}")
        return

    track = Serialize.full_track(out).track
    print(f"{track.title} — {track.subtitle}")
    print(out)  # full dict


if __name__ == "__main__":
    asyncio.run(main())
