"""Voice: text-to-speech and speech-to-text with automatic engine selection.

TTS engines (first available wins unless the user pins one):
  * ``edge``  — Microsoft Edge neural voices (needs ``pip install edge-tts``, best Persian)
  * ``sapi``  — Windows SAPI 5 via PowerShell (works offline on every Windows)
  * ``say``   — macOS
  * ``espeak``/``festival`` — Linux

STT engines:
  * ``openai``/``groq`` Whisper API (best Persian, needs a key)
  * ``faster_whisper`` local model (offline, needs the pip package)
  * ``windows`` SAPI dictation (offline, English-mostly)
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import IS_MAC, IS_WINDOWS, data_dir
from .utils import ensure_dir, run

# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #

PERSIAN_VOICE_HINTS = ("fa-ir", "fa_ir", "persian", "farsi", "داریوش", "هودا", "farid", "dilara", "hedda")


def _edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except Exception:
        return False


def _espeak() -> Optional[str]:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def windows_voices() -> List[str]:
    if not IS_WINDOWS:
        return []
    rc, out, _ = run(
        ["powershell", "-NoProfile", "-Command",
         "Add-Type -AssemblyName System.Speech;"
         "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | "
         "ForEach-Object {$_.VoiceInfo.Name}"],
        timeout=25,
    )
    return [line.strip() for line in (out or "").splitlines() if line.strip()]


def engine_chain(preferred: str = "auto") -> List[str]:
    if preferred and preferred not in ("auto", ""):
        return [preferred]
    chain: List[str] = []
    if _edge_available():
        chain.append("edge")
    if IS_WINDOWS:
        chain.append("sapi")
    if IS_MAC:
        chain.append("say")
    if _espeak():
        chain.append("espeak")
    if shutil.which("festival"):
        chain.append("festival")
    return chain


def speak(text: str, voice: str = "", rate: int = 0, engine: str = "auto",
          block: bool = False) -> Dict[str, Any]:
    """Speak ``text`` aloud.  Returns {"engine": ..., "ok": bool, "error": ...}."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "engine": None, "error": "متنی برای خواندن نیست."}
    for name in engine_chain(engine):
        try:
            if name == "edge":
                _speak_edge(text, voice, rate, block)
            elif name == "sapi":
                _speak_sapi(text, voice, rate, block)
            elif name == "say":
                args = ["say"]
                if voice:
                    args += ["-v", voice]
                args += ["-r", str(180 + rate)]
                args.append(text)
                _spawn(args, block)
            elif name == "espeak":
                args = [_espeak() or "espeak", "-v", "fa" if _is_persian(text) else "en", text]
                _spawn(args, block)
            elif name == "festival":
                proc = subprocess.Popen(["festival", "--tts"], stdin=subprocess.PIPE)
                proc.communicate(text.encode("utf-8"))
            else:
                continue
            return {"ok": True, "engine": name}
        except Exception as exc:
            last = str(exc)
            continue
    return {"ok": False, "engine": None, "error": "هیچ موتور صدایی در دسترس نبود."}


def _spawn(args: List[str], block: bool) -> None:
    kwargs: Dict[str, Any] = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if block:
        subprocess.call(args, **kwargs)
    else:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def _is_persian(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _speak_sapi(text: str, voice: str, rate: int, block: bool) -> None:
    voices = windows_voices()
    chosen = voice
    if not chosen:
        for v in voices:
            if any(h in v.lower() for h in PERSIAN_VOICE_HINTS):
                chosen = v
                break
    if not chosen and voices:
        chosen = voices[0]
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        + (("$s.SelectVoice('%s'); " % chosen.replace("'", "''")) if chosen else "")
        + "$s.Rate=%d; " % max(-10, min(10, int(rate / 10)))
        + "$s.Speak([Console]::In.ReadToEnd())"
    )
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    proc.communicate(text.encode("utf-8")) if block else (proc.stdin.write(text.encode("utf-8")), proc.stdin.close())


EDGE_VOICES = {
    "fa": ["fa-IR-DilaraNeural", "fa-IR-FaridNeural"],
    "en": ["en-US-AriaNeural", "en-US-GuyNeural"],
}


def _speak_edge(text: str, voice: str, rate: int, block: bool) -> None:
    import asyncio

    import edge_tts

    lang = "fa" if _is_persian(text) else "en"
    chosen = voice or EDGE_VOICES[lang][0]
    rate_str = "%+d%%" % int(rate)

    async def _go() -> None:
        communicate = edge_tts.Communicate(text, chosen, rate=rate_str)
        await communicate.save(str(data_dir() / "voices" / "last.mp3"))
        path = data_dir() / "voices" / "last.mp3"
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["afplay", str(path)])
        else:
            for p in ("mpv", "ffplay", "aplay"):
                if shutil.which(p):
                    subprocess.Popen([p, str(path)]) if p != "aplay" else subprocess.Popen([p, str(path)])
                    break

    ensure_dir(data_dir() / "voices")
    if block:
        asyncio.run(_go())
    else:
        import threading

        threading.Thread(target=lambda: asyncio.run(_go()), daemon=True).start()


def save_speech(text: str, path: str, voice: str = "", rate: int = 0) -> str:
    """Render speech to an audio file (WAV on Windows via SAPI, MP3 for edge)."""
    target = Path(os.path.expanduser(path))
    ensure_dir(target.parent)
    if _edge_available() and target.suffix.lower() in (".mp3", ".ogg"):
        import asyncio

        import edge_tts

        lang = "fa" if _is_persian(text) else "en"
        asyncio.run(edge_tts.Communicate(text, voice or EDGE_VOICES[lang][0]).save(str(target)))
        return str(target)
    if IS_WINDOWS:
        script = (
            "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.SetOutputToWaveFile('%s'); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()"
            % str(target).replace("'", "''")
        )
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        proc.communicate(text.encode("utf-8"))
        if target.exists():
            return str(target)
    if _espeak():
        run([_espeak() or "espeak", "-w", str(target), text], timeout=120)
        if target.exists():
            return str(target)
    if IS_MAC:
        run(["say", "-o", str(target), text], timeout=120)
        if target.exists():
            return str(target)
    raise RuntimeError("ساخت فایل صوتی روی این سیستم ممکن نیست.")


# --------------------------------------------------------------------------- #
# Recording (microphone)
# --------------------------------------------------------------------------- #
def record_microphone(seconds: float = 5.0, path: str = "", sample_rate: int = 16000) -> str:
    seconds = max(0.5, min(120.0, float(seconds or 5)))
    if not path:
        path = str(ensure_dir(data_dir() / "voices") / ("rec-%s.wav" % time.strftime("%Y%m%d-%H%M%S")))
    target = Path(path)
    ensure_dir(target.parent)
    if IS_WINDOWS:
        _record_windows(target, seconds, sample_rate)
    elif IS_MAC:
        rc, out, err = run(["ffmpeg", "-y", "-f", "avfoundation", "-i", ":0", "-t", str(seconds),
                            "-ar", str(sample_rate), "-ac", "1", str(target)], timeout=int(seconds) + 60)
        if rc != 0:
            raise RuntimeError("ضبط صدا ناموفق بود (ffmpeg لازم است): %s" % err[-200:])
    else:
        if shutil.which("arecord"):
            rc, out, err = run(["arecord", "-q", "-d", str(int(seconds)), "-f", "S16_LE",
                                "-r", str(sample_rate), "-c", "1", str(target)],
                               timeout=int(seconds) + 60)
            if rc != 0:
                raise RuntimeError("ضبط صدا ناموفق بود: %s" % err[-200:])
        elif shutil.which("ffmpeg"):
            run(["ffmpeg", "-y", "-f", "alsa", "-i", "default", "-t", str(seconds),
                 "-ar", str(sample_rate), "-ac", "1", str(target)], timeout=int(seconds) + 60)
        else:
            raise RuntimeError("برای ضبط صدا arecord یا ffmpeg لازم است.")
    if not target.exists() or target.stat().st_size < 100:
        raise RuntimeError("صدایی ضبط نشد (میکروفون را بررسی کن).")
    return str(target)


def _record_windows(target: Path, seconds: float, sample_rate: int) -> None:
    import ctypes
    from ctypes import wintypes

    winmm = ctypes.windll.winmm
    WAVE_MAPPER = ctypes.c_uint(-1).value
    CALLBACK_NULL = 0

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
            ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
            ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
            ("cbSize", wintypes.WORD),
        ]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
            ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_void_p),
            ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD),
            ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_void_p),
        ]

    fmt = WAVEFORMATEX(1, 1, sample_rate, sample_rate * 2, 2, 16, 0)
    handle = ctypes.c_void_p()
    if winmm.waveInOpen(ctypes.byref(handle), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, CALLBACK_NULL) != 0:
        raise RuntimeError("باز کردن میکروفون ممکن نشد.")
    buf_size = int(sample_rate * 2 * (seconds + 0.5))
    buffer = ctypes.create_string_buffer(buf_size)
    hdr = WAVEHDR(ctypes.cast(buffer, ctypes.c_void_p), buf_size, 0, 0, 0, 0, None, None)
    winmm.waveInPrepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
    winmm.waveInAddBuffer(handle, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
    winmm.waveInStart(handle)
    time.sleep(seconds)
    winmm.waveInStop(handle)
    winmm.waveInReset(handle)
    winmm.waveInUnprepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
    winmm.waveInClose(handle)
    data = ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded)
    with wave.open(str(target), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(data)


# --------------------------------------------------------------------------- #
# Speech to text
# --------------------------------------------------------------------------- #
def transcribe(path: str, engine: str = "auto", api_key: str = "", base_url: str = "",
               model: str = "") -> Dict[str, Any]:
    """Transcribe an audio file.  Returns {"ok", "text", "engine", "error"}."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "text": "", "error": "فایل صوتی پیدا نشد."}
    chain: List[str]
    if engine and engine not in ("auto", ""):
        chain = [engine]
    else:
        chain = []
        if api_key:
            chain.append("whisper_api")
        try:
            import faster_whisper  # noqa: F401

            chain.append("faster_whisper")
        except Exception:
            pass
        if IS_WINDOWS:
            chain.append("windows")
        chain.append("whisper_api")
    last = ""
    for name in chain:
        try:
            if name in ("whisper_api", "openai", "groq"):
                text = _whisper_api(p, api_key, base_url, model)
            elif name == "faster_whisper":
                text = _faster_whisper(p)
            elif name == "windows":
                text = _windows_dictation(p)
            else:
                continue
            if text and text.strip():
                return {"ok": True, "text": text.strip(), "engine": name}
            last = "متنی تشخیص داده نشد."
        except Exception as exc:
            last = str(exc)
    return {"ok": False, "text": "", "error": last or "تبدیل صدا به متن ممکن نشد."}


def _multipart(fields: Dict[str, str], file_field: str, file_path: Path) -> Tuple[bytes, str]:
    boundary = "----DastyarBoundary%s" % int(time.time() * 1000)
    lines: List[bytes] = []
    for key, value in fields.items():
        lines.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, key, value)).encode("utf-8"))
    mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".ogg": "audio/ogg", ".webm": "audio/webm"}.get(file_path.suffix.lower(), "audio/wav")
    lines.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                  "Content-Type: %s\r\n\r\n"
                  % (boundary, file_field, file_path.name, mime)).encode("utf-8"))
    lines.append(file_path.read_bytes())
    lines.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(lines), "multipart/form-data; boundary=%s" % boundary


def _whisper_api(path: Path, api_key: str, base_url: str, model: str) -> str:
    if not api_key:
        raise RuntimeError("کلید API برای تبدیل صدا به متن تنظیم نشده است.")
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/audio/transcriptions"
    body, ctype = _multipart({"model": model or "whisper-1", "language": "fa"}, "file", path)
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + api_key, "Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return data.get("text", "")


def _faster_whisper(path: Path) -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(path), language=None, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


def _windows_dictation(path: Path) -> str:
    if not IS_WINDOWS:
        raise RuntimeError("موتور ویندوز فقط روی ویندوز در دسترس است.")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$r=New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
        "$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
        "$r.SetInputToWaveFile('%s'); "
        "$b=New-Object System.Text.StringBuilder; "
        "while($true){ try { $res=$r.Recognize(); if($res -eq $null){break}; "
        "[void]$b.Append($res.Text + ' ') } catch { break } }; "
        "$r.Dispose(); $b.ToString()" % str(path).replace("'", "''")
    )
    rc, out, err = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=180)
    if rc != 0:
        raise RuntimeError("تشخیص گفتار ویندوز ناموفق بود: %s" % (err or out)[-200:])
    text = (out or "").strip()
    if not text:
        raise RuntimeError("چیزی تشخیص داده نشد (شاید زبان ویندوز فارسی نیست).")
    return text


def available_engines() -> Dict[str, Any]:
    return {
        "tts": engine_chain("auto"),
        "tts_voices": windows_voices() if IS_WINDOWS else [],
        "stt": {
            "whisper_api": True,
            "faster_whisper": _has_module("faster_whisper"),
            "windows": IS_WINDOWS,
        },
        "microphone": True,
    }


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False
