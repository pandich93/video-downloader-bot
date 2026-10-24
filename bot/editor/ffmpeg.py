"""FFmpeg: анализ исходника, расчёт битрейта, перекодирование с прогрессом.

Работает одинаково на Windows и macOS: ffmpeg/ffprobe ищутся в PATH,
вызов — через asyncio subprocess (без shell). На Windows с видеокартой Intel
кодирует через Quick Sync (h264_qsv), при любой ошибке — откат на процессор (libx264).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from bot.editor.options import HOOK_SECONDS, EditOptions
from bot.editor.overlay import OverlayError, Placed, render_hook, render_nick

log = logging.getLogger(__name__)

AUDIO_KBPS = 128
SIZE_MARGIN = 0.92          # оставляем 8% запаса до лимита
MIN_VIDEO_KBPS = 400        # ниже — качество уже неприемлемое
# (длинная сторона, короткая сторона, потолок битрейта видео, кбит/с)
TIERS = ((1920, 1080, 8000), (1280, 720, 4500))

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

ProgressCb = Callable[[int], Awaitable[None]]

# Цветовые стили — встроенные фильтры FFmpeg, без внешних LUT-файлов
STYLE_FILTERS = {
    "warm": "colorbalance=rs=0.06:gs=0.02:bs=-0.06:rm=0.04:bm=-0.04,eq=saturation=1.08",
    "cool": "colorbalance=rs=-0.05:bs=0.07:rm=-0.03:bm=0.05,eq=saturation=1.04",
    "contrast": "eq=contrast=1.12:saturation=1.12:gamma=0.97",
}
FADE_SECONDS = 0.4


class EditFailed(Exception):
    """Ошибка, текст которой можно показать пользователю."""


class FFmpegError(EditFailed):
    """FFmpeg завершился с ошибкой (повод попробовать кодирование на процессоре)."""


@dataclass(frozen=True)
class Probe:
    width: int          # с учётом поворота (видео с телефона)
    height: int
    duration: float
    fps: float
    has_audio: bool


@dataclass(frozen=True)
class Plan:
    frame: str          # crop | blur | original (auto уже раскрыт)
    out_w: int          # размер результата
    out_h: int
    box: int            # для original — максимальная сторона
    start: float
    duration: float     # длительность результата
    video_kbps: int
    limited: bool       # битрейт ограничен размером файла (лимит Telegram)
    audio: bool
    cut_to_limit: bool = False  # обрезано до максимальной длины платформы


@dataclass(frozen=True)
class Variation:
    """Лёгкие случайные отличия: каждый экспорт — отдельный файл с немного другим кадром."""
    zoom: float
    x: float
    y: float
    brightness: float
    contrast: float
    saturation: float
    level: str = "medium"
    seed: int = 0       # по seed (и номеру файла в пакете) вариацию можно повторить для разбора ошибки


@dataclass(frozen=True)
class RenderResult:
    path: Path
    width: int
    height: int
    duration: float
    size: int
    plan: Plan | None = None            # что именно сделано — для подписи к видео
    variation: Variation | None = None


def missing_tools() -> list[str]:
    return [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]


def _popen_kwargs() -> dict:
    if sys.platform == "win32":
        # без окна консоли и с пониженным приоритетом — ноутбук не тормозит во время обработки
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    return {}


def _with_low_priority(cmd: list[str]) -> list[str]:
    if sys.platform != "win32" and shutil.which("nice"):
        return ["nice", "-n", "10", *cmd]
    return cmd


# ---------- выбор кодировщика ----------

CPU_ENCODER = "libx264"
QSV_ENCODER = "h264_qsv"
_encoder: str | None = None


async def _encoder_works(name: str) -> bool:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "color=c=black:s=256x256:d=0.2", "-vf", "format=nv12", "-c:v", name, "-f", "null", "-"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **_popen_kwargs())
        return await asyncio.wait_for(proc.wait(), 20) == 0
    except (OSError, asyncio.TimeoutError):
        return False


async def pick_encoder(preference: str = "auto") -> str:
    """auto / qsv — видеокарта Intel, если работает; cpu — всегда процессор."""
    global _encoder
    if preference == "cpu":
        return CPU_ENCODER
    if _encoder is None:
        _encoder = QSV_ENCODER if await _encoder_works(QSV_ENCODER) else CPU_ENCODER
        log.info("Кодировщик видео: %s", _encoder)
    return _encoder


def _disable_hw() -> None:
    global _encoder
    _encoder = CPU_ENCODER


# ---------- анализ исходника ----------

def _fps(value: str | None) -> float:
    try:
        num, _, den = (value or "").partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _rotation(stream: dict) -> int:
    tags = stream.get("tags") or {}
    try:
        if "rotate" in tags:
            return abs(int(float(tags["rotate"])))
        for sd in stream.get("side_data_list") or []:
            if "rotation" in sd:
                return abs(int(float(sd["rotation"])))
    except ValueError:
        pass
    return 0


async def probe(path: Path) -> Probe:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **_popen_kwargs())
    out, err = await asyncio.wait_for(proc.communicate(), 60)
    if proc.returncode != 0:
        log.warning("ffprobe: %s", err.decode(errors="replace")[-500:])
        raise EditFailed("😕 Не удалось прочитать видео.")

    data = json.loads(out or b"{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise EditFailed("😕 В файле нет видеодорожки.")
    w, h = int(video["width"]), int(video["height"])
    if _rotation(video) % 180 == 90:
        w, h = h, w
    duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise EditFailed("😕 Не удалось определить длительность видео.")
    fps = _fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate")) or 30.0
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return Probe(w, h, duration, fps, has_audio)


# ---------- план: кадр, длительность, битрейт ----------

def _even(x: float) -> int:
    return max(2, int(x) // 2 * 2)


def make_plan(p: Probe, o: EditOptions, max_bytes: int,
              tier: int = 0, kbps_factor: float = 1.0) -> Plan:
    if o.start >= p.duration - 0.5:
        raise EditFailed(f"✂️ Начало фрагмента дальше конца видео (длина {p.duration:.0f} с).")
    end = min(o.end, p.duration) if o.end is not None else p.duration
    usable = end - o.start
    if usable < 1:
        raise EditFailed("✂️ Фрагмент получился короче секунды.")
    duration = min(usable / o.speed, o.max_duration)

    frame = o.frame
    if frame == "auto":
        ratio = p.height / p.width
        # уже вертикальное (около 9:16) — заполняем кадр, иначе — размытый фон без потери содержимого
        frame = "crop" if 1.5 <= ratio <= 2.0 else "blur"

    audio = p.has_audio and o.audio != "mute"
    audio_kbps = AUDIO_KBPS if audio else 0
    budget_kbps = max_bytes * SIZE_MARGIN * 8 / 1000 / duration
    video_kbps = int((budget_kbps - audio_kbps) * kbps_factor)

    if video_kbps < MIN_VIDEO_KBPS:
        max_minutes = max_bytes * SIZE_MARGIN * 8 / 1000 / (MIN_VIDEO_KBPS + audio_kbps) / 60
        raise EditFailed(
            f"📦 Видео слишком длинное: в {max_bytes // 2**20} МБ не уложить нормальное качество.\n"
            f"Выберите фрагмент примерно до {max_minutes:.0f} мин.")

    # 1080p — только если исходник не меньше ~1080p и битрейта хватает, иначе 720p
    if tier == 0 and (min(p.width, p.height) < 1000 or video_kbps < 2500):
        tier = 1
    long_side, short_side, cap = TIERS[tier]
    limited = video_kbps < cap
    video_kbps = min(video_kbps, cap)

    if frame == "original":
        f = min(1.0, long_side / max(p.width, p.height))
        out_w, out_h = _even(p.width * f), _even(p.height * f)
    else:
        out_w, out_h = short_side, long_side
    cut = usable / o.speed > o.max_duration + 0.5
    return Plan(frame, out_w, out_h, long_side, o.start, duration, video_kbps, limited, audio, cut)


# Диапазоны вариации по уровням; «слабая» — примерно вдвое мягче «средней»
VARIATION_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "medium": {"zoom": (1.02, 1.05), "x": (0.0, 1.0), "y": (0.0, 1.0),
               "brightness": (-0.03, 0.03), "contrast": (0.97, 1.04), "saturation": (0.95, 1.08)},
    "light": {"zoom": (1.01, 1.025), "x": (0.0, 1.0), "y": (0.0, 1.0),
              "brightness": (-0.015, 0.015), "contrast": (0.985, 1.02), "saturation": (0.975, 1.04)},
}
BAND_PAD = 0.15     # отступ от краёв полосы — у соседних файлов пакета значения не сливаются


def random_variations(n: int, level: str = "medium", seed: int | None = None) -> list[Variation]:
    """n вариаций, заметно отличающихся друг от друга.

    Диапазон каждого параметра делится на n полос, каждому файлу достаётся своя полоса
    (в случайном порядке). Для одного файла — просто случайное значение из всего диапазона.
    """
    ranges = VARIATION_RANGES[level]
    seed = secrets.randbits(32) if seed is None else seed
    rng = random.Random(seed)
    pad = BAND_PAD if n > 1 else 0.0
    bands = {k: rng.sample(range(n), n) for k in ranges}
    result = []
    for i in range(n):
        values = {}
        for k, (lo, hi) in ranges.items():
            u = (bands[k][i] + rng.uniform(pad, 1 - pad)) / n
            values[k] = round(lo + (hi - lo) * u, 4 if k == "zoom" else 3)
        result.append(Variation(**values, level=level, seed=seed))
    return result


def random_variation(level: str = "medium", seed: int | None = None) -> Variation:
    return random_variations(1, level, seed)[0]


@dataclass(frozen=True)
class Overlays:
    """Графика поверх видео (PNG): логотип, ник, хук."""
    logo: Path | None = None
    nick: Placed | None = None
    hook: Placed | None = None


HOOK_FADE = 0.3


def build_filter(p: Probe, o: EditOptions, plan: Plan, var: Variation | None, *,
                 pix_fmt: str = "yuv420p", ov: Overlays = Overlays(),
                 brand_color: str = "FFFFFF") -> str:
    """Граф для -filter_complex. Без пробелов — безопасно для командной строки Windows.

    Входы: 0 — видео, дальше по порядку логотип, ник, хук (те, что есть).
    """
    pre: list[str] = []
    if var:
        z = var.zoom
        pre.append(f"crop=w=trunc(iw/{z}/2)*2:h=trunc(ih/{z}/2)*2:x=(iw-ow)*{var.x}:y=(ih-oh)*{var.y}")
    if o.speed != 1:
        pre.append(f"setpts=PTS/{o.speed}")
    if p.fps > 60.5:
        pre.append("fps=60")
    head = "[0:v]" + "".join(f"{f}," for f in pre)
    color = f",eq=brightness={var.brightness}:contrast={var.contrast}:saturation={var.saturation}" if var else ""
    if o.style in STYLE_FILTERS:
        color += "," + STYLE_FILTERS[o.style]

    W, H = plan.out_w, plan.out_h
    if plan.frame == "crop":
        graph = f"{head}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}{color}[base]"
    elif plan.frame == "blur":
        bw, bh = _even(W / 4), _even(H / 4)  # фон размываем в маленьком размере — так в разы быстрее
        graph = (
            f"{head}split=2[bg][fg];"
            f"[bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"boxblur=10:2,scale={W}:{H}[bgb];"
            f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2{color}[base]"
        )
    else:
        # ровно размер из плана: после зума вариации кадр не мельчает, а оверлеи
        # (хук, ник, логотип) рассчитаны под этот размер. Пропорции те же — кроп их сохраняет
        # с точностью до пары пикселей округления
        graph = f"{head}scale={W}:{H}{color}[base]"

    cur, idx = "base", 1
    if ov.logo:
        lw = _even(W * (0.18 if H > W else 0.12))
        m = _even(min(W, H) * 0.04)
        graph += (f";[{idx}:v]scale={lw}:-2,format=rgba,colorchannelmixer=aa=0.85[logo];"
                  f"[{cur}][logo]overlay=W-w-{m}:{m}[withlogo]")
        cur, idx = "withlogo", idx + 1
    if ov.nick:
        graph += f";[{cur}][{idx}:v]overlay={ov.nick.x}:{ov.nick.y}[withnick]"
        cur, idx = "withnick", idx + 1
    if o.progress:
        # полоса прогресса: подложка + полоса фирменного цвета, растущая слева направо
        bh = max(6, _even(min(W, H) * 0.008))
        d = f"{plan.duration:.3f}"
        graph += (f";[{cur}]drawbox=x=0:y=ih-{bh}:w=iw:h={bh}:color=white@0.25:t=fill[track];"
                  f"color=c=0x{brand_color}:s={W}x{bh}:r=30:d={d}[bar];"
                  f"[track][bar]overlay=x='-w+w*t/{d}':y=H-h[withbar]")
        cur = "withbar"
    if ov.hook:
        # хук: проявляется и чуть выезжает снизу за 0,3 с, к концу 3-й секунды исчезает
        h = ov.hook
        dy = max(8, int(h.height * 0.12))
        out_at = HOOK_SECONDS - 0.4
        graph += (f";[{idx}:v]format=rgba,fade=t=in:st=0:d={HOOK_FADE}:alpha=1,"
                  f"fade=t=out:st={out_at}:d=0.4:alpha=1[hook];"
                  f"[{cur}][hook]overlay=x={h.x}:y='{h.y}+{dy}*(1-min(t/{HOOK_FADE},1))':"
                  f"eof_action=pass[withhook]")
        cur, idx = "withhook", idx + 1

    final: list[str] = []
    if o.fade_in:
        final.append(f"fade=t=in:st=0:d={FADE_SECONDS}")
    final += ["setsar=1", f"format={pix_fmt}"]
    graph += f";[{cur}]{','.join(final)}[v]"

    if plan.audio:
        af = []
        if o.speed != 1:
            af.append(f"atempo={o.speed}")
        if o.audio == "norm":
            af.append("loudnorm=I=-14:TP=-1.5:LRA=11")  # около -14 LUFS — ориентир соцсетей
        if o.fade_in:
            af.append(f"afade=t=in:st=0:d={FADE_SECONDS}")
        af.append("aresample=48000")
        graph += f";[0:a:0]{','.join(af)}[a]"
    return graph


def _video_args(encoder: str, plan: Plan) -> list[str]:
    k = plan.video_kbps
    if encoder == QSV_ENCODER:
        rate = (["-b:v", f"{k}k", "-maxrate", f"{k}k", "-bufsize", f"{2 * k}k"] if plan.limited
                else ["-global_quality", "22"])
        return ["-c:v", QSV_ENCODER, "-preset", "veryfast", *rate, "-profile:v", "high", "-pix_fmt", "nv12"]
    return ["-c:v", CPU_ENCODER, "-preset", "veryfast", "-crf", "21" if plan.limited else "20",
            "-maxrate", f"{k}k", "-bufsize", f"{2 * k}k", "-profile:v", "high", "-pix_fmt", "yuv420p"]


def build_command(src: Path, dst: Path, p: Probe, o: EditOptions, plan: Plan,
                  var: Variation | None, *, encoder: str = CPU_ENCODER,
                  ov: Overlays = Overlays(), brand_color: str = "FFFFFF") -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats"]
    if plan.start:
        cmd += ["-ss", f"{plan.start:.3f}"]
    cmd += ["-i", str(src)]
    if ov.logo:
        cmd += ["-i", str(ov.logo)]
    if ov.nick:
        cmd += ["-i", str(ov.nick.path)]
    if ov.hook:
        cmd += ["-loop", "1", "-framerate", "30", "-t", f"{HOOK_SECONDS + 0.2}", "-i", str(ov.hook.path)]
    pix_fmt = "nv12" if encoder == QSV_ENCODER else "yuv420p"
    cmd += ["-filter_complex", build_filter(p, o, plan, var, pix_fmt=pix_fmt, ov=ov,
                                            brand_color=brand_color),
            "-map", "[v]"]
    if plan.audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += [
        "-t", f"{plan.duration:.3f}",
        *_video_args(encoder, plan),
        # очистка метаданных: дата, устройство, геометка, название программы-кодировщика
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-sn", "-dn", "-movflags", "+faststart",
        str(dst),
    ]
    return cmd


# ---------- запуск ----------

async def run_ffmpeg(cmd: list[str], duration: float, on_progress: ProgressCb | None = None,
                     timeout: float | None = None, cwd: Path | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *_with_low_priority(cmd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None, **_popen_kwargs())
    errors: list[bytes] = []

    async def read_errors() -> None:
        while chunk := await proc.stderr.read(4096):
            errors.append(chunk)

    async def read_progress() -> None:
        last = 0.0
        while line := await proc.stdout.readline():
            key, _, value = line.decode(errors="replace").strip().partition("=")
            if key == "out_time_us" and value.isdigit() and on_progress and duration > 0:
                now = time.monotonic()
                if now - last >= 4:  # не чаще раза в 4 секунды — лимиты Telegram на правку сообщений
                    last = now
                    await on_progress(min(99, int(int(value) / 1e6 / duration * 100)))

    try:
        await asyncio.wait_for(asyncio.gather(read_errors(), read_progress(), proc.wait()), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise EditFailed("⏱ Обработка заняла слишком много времени и была остановлена.") from None
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        raise

    if proc.returncode != 0:
        log.warning("ffmpeg завершился с кодом %s: %s", proc.returncode,
                    b"".join(errors).decode(errors="replace")[-1500:])
        raise FFmpegError("😕 FFmpeg не смог обработать видео.")


def _overlays(o: EditOptions, plan: Plan, workdir: Path, logo: Path | None, nick: str) -> Overlays:
    try:
        return Overlays(
            logo=logo if o.logo else None,
            nick=render_nick(nick, plan.out_w, plan.out_h, workdir / "nick.png") if o.nick and nick else None,
            hook=render_hook(o.hook, plan.out_w, plan.out_h, workdir / "hook.png") if o.hook else None,
        )
    except OverlayError as e:
        raise EditFailed(str(e)) from e


async def render(src: Path, workdir: Path, o: EditOptions, max_bytes: int,
                 on_progress: ProgressCb | None = None, *, encoder_pref: str = "auto",
                 logo: Path | None = None, brand_color: str = "FFFFFF",
                 nick: str = "", variation: Variation | None = None) -> RenderResult:
    """Обрабатывает видео и гарантирует размер результата не больше max_bytes.

    variation — заранее выбранная вариация (пакет из нескольких файлов); без неё — случайная.
    """
    src, workdir = src.resolve(), workdir.resolve()   # FFmpeg запускается из workdir
    if logo:
        logo = logo.resolve()
    p = await probe(src)
    var = None if o.variation == "off" else (variation or random_variation(o.variation))
    if o.logo and not (logo and logo.is_file()):
        raise EditFailed("🖼 Логотип не найден: положите PNG в папку assets под именем logo.png.")
    encoder = await pick_encoder(encoder_pref)
    out = workdir / f"edit_{secrets.token_hex(4)}.mp4"

    # Вторая попытка — если оценка размера промахнулась: 720p и битрейт на 25% ниже
    for tier, factor in ((0, 1.0), (1, 0.75)):
        plan = make_plan(p, o, max_bytes, tier, factor)
        ov = _overlays(o, plan, workdir, logo, nick)
        log.info("Обработка (%s): %s, %s; вариация: %s", encoder, o, plan, var)
        while True:
            cmd = build_command(src, out, p, o, plan, var, encoder=encoder, ov=ov,
                                brand_color=brand_color)
            try:
                await run_ffmpeg(cmd, plan.duration, on_progress,
                                 timeout=300 + plan.duration * 8, cwd=workdir)
                break
            except FFmpegError:
                if encoder == CPU_ENCODER:
                    raise
                log.warning("Кодирование на видеокарте не удалось — переключаюсь на процессор")
                _disable_hw()
                encoder = CPU_ENCODER
        size = out.stat().st_size
        if size <= max_bytes:
            res = await probe(out)
            return RenderResult(out, res.width, res.height, res.duration, size, plan, var)
        log.info("Результат %.1f МБ больше лимита — повтор с меньшим битрейтом", size / 2**20)
        out.unlink(missing_ok=True)

    raise EditFailed(f"📦 Не удалось уложить видео в {max_bytes // 2**20} МБ. Выберите фрагмент короче.")


async def make_thumbnail(video: Path, duration: float) -> Path | None:
    """Обложка-превью для отправки через MTProto (Telegram сам её не делает)."""
    thumb = video.with_suffix(".jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{min(1.0, duration / 2):.2f}",
           "-i", str(video), "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", str(thumb)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **_popen_kwargs())
        if await asyncio.wait_for(proc.wait(), 30) == 0 and thumb.is_file():
            return thumb
    except (OSError, asyncio.TimeoutError):
        pass
    return None
