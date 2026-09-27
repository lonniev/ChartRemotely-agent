"""Hearing one spoken sentence, on this Mac, with Whisper.

Siri's dictation matches against all of English and hands back three
separate answers. Whisper (``mlx-whisper``, on the Mac's GPU) hears the whole
sentence - "Palantir, half, on mac mini" - and is *primed* with the words this
Mac expects: the ten scale mnemonics, the bar phrases, the companies the owner
charts and the names of their displays. Priming is what turns "Palantir Hath
on Mac Mini." into "Palantir half on mac mini."; :mod:`understand` then
recovers the company, scale and display from the text.

Three rules:

* **No ffmpeg.** macOS's own ``afconvert`` turns the recording (m4a, caf,
  wav - whatever the Shortcut sent) into 16 kHz mono 16-bit PCM, in a private
  temporary folder that is removed before the reply.
* **Never log audio.** Only the text heard is logged, by the caller.
* **Typing is the fallback.** A recording with nothing in it - empty, a
  bare header, silence, noise Whisper hears only filler in - raises
  :class:`Unheard`, and :mod:`voice` answers with the typing box instead of a
  sentence to speak.
* **Lazy.** ``mlx_whisper`` and ``numpy`` are imported only when a sentence
  is actually heard, so this module imports anywhere (CI runs on Linux).

The model is ``whisper-large-v3-turbo`` (about 1.6 GB, from Hugging Face on
first use; ``chartremotely setup`` fetches it ahead of time). The listener
warms it once at start, in the background, and keeps it loaded: the first
sentence then takes about a second, not three.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
import tempfile
import threading
import wave
from array import array
from collections.abc import Callable, Iterable
from pathlib import Path

from . import resolve, scales

MODEL = "mlx-community/whisper-large-v3-turbo"
MODEL_SIZE = "about 1.6 GB"
RATE = 16_000
#: Longest recording accepted, in bytes and in seconds of speech.
MAX_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 15.0
#: Whisper reads at most 224 prompt tokens; English runs about four
#: characters a token, so this keeps the prompt near 200.
PROMPT_CHARS = 800
#: Smaller than any real recording: a Shortcut that captured nothing still
#: sends an m4a header (28 bytes on a Mac mini, which has no microphone).
MIN_BYTES = 512
#: Shorter than a word, or quieter than a room (RMS of 16-bit samples, about
#: -56 dBFS): nothing was said.
MIN_SECONDS = 0.3
SILENCE_RMS = 50
#: What Whisper "hears" in silence or noise, lower-cased, punctuation dropped.
FILLER = frozenset({"you", "thank you", "thanks", "thank you very much", "thanks for watching",
                    "thank you for watching", "bye", "bye bye", "uh", "um", "hmm", "mm", "ah",
                    "oh", "so", "okay", "ok", "the", "music", "silence", "applause"})
AFCONVERT = "/usr/bin/afconvert"

#: The bar phrases people say instead of a mnemonic.
BAR_PHRASES = ("thirty minutes", "an hour", "four hours", "a day", "a week", "as is")
#: Recording formats afconvert is asked to read, by what the Shortcut declares.
SUFFIX = {"audio/m4a": ".m4a", "audio/x-m4a": ".m4a", "audio/mp4": ".m4a", "audio/aac": ".m4a",
          "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
          "audio/x-caf": ".caf", "audio/caf": ".caf"}


class HearingError(RuntimeError):
    """The recording could not be read or transcribed; the text is fit to speak."""


class Unheard(HearingError):
    """Nothing usable was recorded - no microphone, silence, noise, an unreadable
    file, or a Mac that cannot hear yet. Answered with the typing box, not spoken."""


def supported() -> bool:
    """Is this an Apple-silicon Mac, where MLX runs?"""
    return sys.platform == "darwin" and platform.machine() == "arm64"


def available() -> bool:
    """Can this Mac hear? Apple silicon with ``mlx-whisper`` installed."""
    if not supported():
        return False
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        return False
    return True


# -- the recording ----------------------------------------------------------------

def suffix_for(content_type: str | None) -> str:
    """The file suffix afconvert should read the recording as; m4a when unsure."""
    kind = (content_type or "").split(";")[0].strip().lower()
    return SUFFIX.get(kind, ".m4a")


def read_pcm(path: Path) -> bytes:
    """The 16-bit mono frames of a WAV file afconvert wrote, refusing anything else."""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise Unheard("The recording was not in a shape I can hear.")
        if wav.getnframes() > MAX_SECONDS * wav.getframerate():
            raise HearingError(f"That was longer than {int(MAX_SECONDS)} seconds. Say it shorter.")
        return wav.readframes(wav.getnframes())


def decode(audio: bytes, content_type: str | None = None,
           run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bytes:
    """A recording, as 16 kHz mono 16-bit PCM. Nothing is left on disk after."""
    if len(audio) < MIN_BYTES:
        raise Unheard("I didn't hear anything.")
    if len(audio) > MAX_BYTES:
        raise HearingError(f"That was longer than {int(MAX_SECONDS)} seconds. Say it shorter.")
    with tempfile.TemporaryDirectory(prefix="chartremotely-hear-") as folder:
        source = Path(folder) / f"said{suffix_for(content_type)}"
        target = Path(folder) / "said.wav"
        source.write_bytes(audio)
        done = run([AFCONVERT, "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1",
                    str(source), str(target)], capture_output=True, check=False, timeout=20)
        if done.returncode != 0 or not target.exists():
            raise Unheard("I couldn't read that recording.")
        return read_pcm(target)


def usable(pcm: bytes) -> bool:
    """Was anything said? At least :data:`MIN_SECONDS` long and louder than silence."""
    if len(pcm) < MIN_SECONDS * RATE * 2:
        return False
    frames = array("h")
    frames.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder != "little":
        frames.byteswap()
    return (sum(x * x for x in frames) / len(frames)) ** 0.5 >= SILENCE_RMS


def filler(text: str) -> bool:
    """Is this what Whisper makes of silence or noise, rather than a request?"""
    words = " ".join(re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split())
    return not words or words in FILLER


def samples(pcm: bytes):
    """PCM frames as the float32 waveform Whisper takes (numpy, imported here)."""
    import numpy as np

    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


# -- priming ----------------------------------------------------------------------

def companies(recent: Iterable[str], rows: list[dict]) -> list[str]:
    """The spoken names of recently charted symbols, most recent first."""
    names = {r["t"]: r["n"] for r in rows}
    out: list[str] = []
    for ticker in recent:
        name = resolve.spoken_name(names[ticker]) if ticker in names else ticker
        if name and name not in out:
            out.append(name)
    return out


def prompt(recent: Iterable[str], rows: list[dict], displays: Iterable[str],
           limit: int = PROMPT_CHARS) -> str:
    """The priming text: an example sentence, then the words this Mac expects.

    Scales and displays always fit; companies fill what room is left, most
    recent first, and the whole is cut at ``limit`` characters.
    """
    places = [d.strip() for d in displays if d and d.strip()]
    names = companies(recent, rows)
    example = f"{names[0] if names else 'Palantir'} half on {places[0] if places else 'mac mini'}."
    head = (f"{example} Scales: {', '.join(scales.MNEMONIC.values())}, "
            f"{', '.join(BAR_PHRASES)}.")
    if places:
        head += f" Displays: {', '.join(places)}."
    text = head
    if names:
        kept: list[str] = []
        for name in names:
            candidate = f"{head} Companies: {', '.join(kept + [name])}."
            if len(candidate) > limit:
                break
            kept.append(name)
        if kept:
            text = f"{head} Companies: {', '.join(kept)}."
    return text[:limit]


# -- the model --------------------------------------------------------------------

_lock = threading.Lock()


def _transcribe(audio, initial_prompt: str | None) -> str:
    import mlx_whisper

    result = mlx_whisper.transcribe(audio, path_or_hf_repo=MODEL, initial_prompt=initial_prompt,
                                    language="en", temperature=0.0,
                                    condition_on_previous_text=False)
    return " ".join(str(result.get("text") or "").split())


def transcribe(pcm: bytes, initial_prompt: str | None = None) -> str:
    """What was said, as text. One sentence at a time: the GPU is not shared."""
    with _lock:
        try:
            return _transcribe(samples(pcm), initial_prompt)
        except ImportError:
            raise Unheard("This Mac cannot hear yet. Run chartremotely setup.") from None


def warm() -> bool:
    """Load the model once (a second of silence), so the first sentence is quick.

    Returns whether it loaded. Never raises: a listener that cannot hear still
    answers every other request.
    """
    if not available():
        return False
    try:
        transcribe(bytes(RATE * 2))
    except Exception:  # noqa: BLE001 - warming is best effort
        return False
    return True


def warm_in_background() -> threading.Thread:
    """Start :func:`warm` on its own thread and return it."""
    thread = threading.Thread(target=warm, name="warm-whisper", daemon=True)
    thread.start()
    return thread


def fetch_model(say: Callable[[str], None] = print) -> bool:
    """Download the model ahead of the first sentence (setup's step). Shows progress.

    Returns whether it is ready. Skipped, with a reason, where it cannot run.
    """
    if not supported():
        say("Hearing needs an Apple-silicon Mac; the Shortcut offers a typing box instead.")
        return False
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        say("The speech model's downloader is missing; reinstall ChartRemotely, then run setup.")
        return False
    say(f"Fetching the speech model ({MODEL_SIZE}, once; later runs skip this)…")
    snapshot_download(repo_id=MODEL)
    say("The speech model is on this Mac.")
    return True
