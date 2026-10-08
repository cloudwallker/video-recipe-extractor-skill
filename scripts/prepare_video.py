#!/usr/bin/env python3
"""为视频菜谱分析准备可核验的字幕、音频和原始视频帧（Python 3.9+）。"""
import argparse
import html
import importlib.util
import ipaddress
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit


def check():
    dependencies = {name: bool(shutil.which(name)) for name in ("ffmpeg", "ffprobe", "yt-dlp")}
    dependencies.update({"Pillow": importlib.util.find_spec("PIL") is not None,
                         "faster_whisper": importlib.util.find_spec("faster_whisper") is not None})
    return {"dependencies": dependencies,
            "prepare_ready": all(dependencies[k] for k in ("ffmpeg", "ffprobe", "Pillow")),
            "fetch_ready": all(dependencies[k] for k in ("yt-dlp", "ffmpeg"))}


def require_tool(name):
    if not shutil.which(name):
        raise RuntimeError("缺少依赖 " + name + "；请先安装并加入 PATH。")


def run_tool(command, label, timeout=120):
    # 永远捕获外部日志：下载器报错可能含 URL、请求头或带凭据的配置。
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(label + "失败或超时；请检查依赖、输入与访问权限。") from None
    if result.returncode:
        raise RuntimeError(label + "失败；请检查输入格式或访问权限，不会自动重试。")
    return result.stdout


def empty_output(out_dir):
    out_dir = Path(out_dir).resolve()
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise ValueError("输出目录必须不存在或为空；不能覆盖已有文件，请使用新的目录。")
    return out_dir


def validate_url(url):
    message = "URL 仅支持无凭据的公网 http(s) 地址；请移除认证参数或改用本地视频。"
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in ("http", "https") or not host or parsed.username is not None:
            raise ValueError(message)
        if parsed.port is not None and not 0 < parsed.port < 65536:
            raise ValueError(message)
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or host.endswith((".local", ".localhost"))
                    or re.fullmatch(r"[0-9.]+", host)):
                raise ValueError(message)
        else:
            if not address.is_global:
                raise ValueError(message)
        sensitive = r"token|secret|pass(word|wd)?|pwd|auth|credential|cookie|session|signature|jwt|api.?key|access.?key|^(sig|key|code)$"
        if any(re.search(sensitive, key, re.I) for key, _ in parse_qsl(parsed.query)):
            raise ValueError(message)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except (ValueError, TypeError):
        raise ValueError(message) from None


def fetch(url, out_dir):
    url = validate_url(url)
    out_dir = empty_output(out_dir)
    require_tool("yt-dlp")
    require_tool("ffmpeg")
    out_dir.mkdir(parents=True, exist_ok=True)
    common = ["yt-dlp", "--ignore-config", "--no-cookies", "--no-cookies-from-browser",
              "--no-playlist", "--playlist-items", "1", "--no-progress", "--quiet", "--no-warnings",
              "--socket-timeout", "30", "--retries", "0", "--fragment-retries", "0",
              "--extractor-retries", "0", "--file-access-retries", "0", "--no-overwrites",
              "--xff", "never", "-o", str(out_dir / "source.%(ext)s")]
    raw = run_tool(common + ["--no-write-subs", "--no-write-auto-subs", "--no-write-info-json",
                            "--no-embed-subs", "--dump-single-json", "--no-simulate", "-f",
                            "bv*+ba/b", "--merge-output-format", "mp4", "--", url],
                   "视频下载", timeout=600)
    try:
        info = json.loads(raw)
        if not isinstance(info, dict) or info.get("_type") in ("playlist", "multi_video"):
            raise ValueError()
    except (ValueError, TypeError):
        raise RuntimeError("下载元数据无效；仅支持单个视频。") from None
    videos = sorted(p for p in out_dir.glob("source.*") if p.suffix.lower() in
                    (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts"))
    if len(videos) != 1:
        raise RuntimeError("没有得到唯一完整视频；请检查来源或改用本地视频。")
    # 仅保存白名单元数据，不落盘 CDN 签名 URL、请求头或账户字段。
    metadata = {"source": {"kind": "online_video", "url": url},
                "id": info.get("id"), "title": info.get("title"),
                "extractor": info.get("extractor"), "duration_seconds": info.get("duration"),
                "video_path": videos[0].name, "subtitle_paths": [], "subtitle_status": "pending"}
    metadata_path = out_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        run_tool(common + ["--skip-download", "--write-subs", "--write-auto-subs",
                           "--sub-langs", "zh.*,en.*", "--sub-format", "vtt/srt/best",
                           "--no-write-info-json", "--", url], "字幕下载", timeout=600)
    except RuntimeError:
        metadata["subtitle_status"] = "failed"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    metadata["subtitle_paths"] = sorted(p.name for p in out_dir.glob("source.*")
                                        if p.suffix.lower() in (".vtt", ".srt"))
    metadata["subtitle_status"] = "available" if metadata["subtitle_paths"] else "missing"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"metadata": "metadata.json", "video_path": metadata["video_path"],
            "subtitle_paths": metadata["subtitle_paths"], "subtitle_status": metadata["subtitle_status"]}


def timestamp(value):
    match = re.fullmatch(r"(?:(\d{2,}):)?(\d{2}):(\d{2})[.,](\d{3})", value)
    if not match:
        raise ValueError("字幕时间戳格式无效；需要 SRT/VTT 的毫秒时间戳。")
    hours, minutes, seconds, milliseconds = match.groups()
    if int(minutes) > 59 or int(seconds) > 59:
        raise ValueError("字幕时间戳中的分或秒无效。")
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


def clean_text(text):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", text)).split())


def remove_overlap(previous, text):
    pattern = r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*|[\u3400-\u9fff]|[^\s]"
    old = [m.group().casefold() for m in re.finditer(pattern, previous)]
    spans = list(re.finditer(pattern, text))
    new = [m.group().casefold() for m in spans]
    for count in range(min(len(old), len(new)), 0, -1):
        if old[-count:] == new[:count]:
            return text[spans[count].start():] if count < len(spans) else ""
    return text


def parse_subtitles(path, duration):
    path = Path(path)
    if path.suffix.lower() not in (".srt", ".vtt"):
        raise ValueError("字幕仅支持 UTF-8 的 .srt 或 .vtt 文件。")
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
    segments, previous_text, previous_start, previous_end = [], "", -1.0, -1.0
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        time_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_index is None:
            raise ValueError("字幕块缺少有效时间戳。")
        match = re.fullmatch(r"(\S+)\s+-->\s+(\S+)(?:\s+.*)?", lines[time_index])
        if not match:
            raise ValueError("字幕时间戳格式无效。")
        start, end = map(timestamp, match.groups())
        if start < previous_start or end <= start or end > duration + 0.001:
            raise ValueError("字幕时间戳逆序或超出视频时长。")
        raw = clean_text(" ".join(lines[time_index + 1:]))
        rolling = path.suffix.lower() == ".vtt" and start < previous_end
        text = remove_overlap(previous_text, raw) if rolling else raw
        previous_text, previous_start, previous_end = raw, start, end
        if text:
            segment = {"id": "s%03d" % (len(segments) + 1), "start": start, "end": end,
                       "text": text, "kind": "subtitle"}
            if raw != text:
                segment["raw_text"] = raw
            segments.append(segment)
    return segments


def frame_times(duration, interval=10, max_frames=24, at=None):
    if (not math.isfinite(duration) or duration <= 0 or not math.isfinite(interval)
            or interval <= 0 or max_frames < 1 or not math.isfinite(duration / interval)):
        raise ValueError("视频时长、取帧间隔与最大帧数必须是有限正数。")
    if at:
        if any(not math.isfinite(t) or t < 0 or t >= duration for t in at):
            raise ValueError("取帧时间必须在视频时长内，且不能等于结尾。")
        times = sorted(set(float(t) for t in at))
        if len(times) > max_frames:
            raise ValueError("指定时间点超过最大帧数；请增加 --max-frames 或减少 --at。")
        return times
    count = max(1, math.ceil(duration / interval))
    indices = (range(count) if count <= max_frames else
               [i * (count - 1) // (max_frames - 1) for i in range(max_frames)] if max_frames > 1 else [0])
    return [round(i * interval, 6) for i in indices]


def probe_video(video):
    info = json.loads(run_tool(["ffprobe", "-v", "error", "-show_entries",
                               "format=duration:stream=codec_type,avg_frame_rate", "-of", "json", str(video)],
                              "视频探测"))
    try:
        duration = float(info["format"]["duration"])
        streams = {stream.get("codec_type") for stream in info["streams"]}
        if not math.isfinite(duration) or duration <= 0 or "video" not in streams:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise ValueError("输入需要包含视频流及有效时长。") from None
    try:
        rate = next(s.get("avg_frame_rate", "0/0") for s in info["streams"] if s.get("codec_type") == "video")
        numerator, denominator = map(float, rate.split("/"))
        frame_span = max(2.0, 2 * denominator / numerator) if numerator > 0 and denominator > 0 else duration
        if not math.isfinite(frame_span):
            frame_span = duration
    except (TypeError, ValueError):
        frame_span = duration
    return duration, "audio" in streams, frame_span


def format_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return "%02d:%02d:%02d.%03d" % (hours, minutes, seconds, milliseconds)


def contact_sheet(out_dir, frames):
    from PIL import Image, ImageDraw
    columns = min(4, len(frames))
    sheet = Image.new("RGB", (columns * 320, math.ceil(len(frames) / columns) * 210), "#202020")
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        x, y = index % columns * 320, index // columns * 210
        with Image.open(out_dir / frame["path"]) as image:
            image.thumbnail((320, 180))
            sheet.paste(image, (x + (320 - image.width) // 2, y + (180 - image.height) // 2))
        draw.text((x + 8, y + 188), frame["id"] + "  " + format_time(frame["time"]), fill="white")
    sheet.save(out_dir / "contact-sheet.jpg", quality=90)


def transcribe_audio(audio, duration, model):
    print("已启用本地转写；模型未缓存时 faster-whisper 会下载模型。", file=sys.stderr)
    try:
        from faster_whisper import WhisperModel
        recognizer = WhisperModel(model, device="cpu", compute_type="int8")
        detected, _ = recognizer.transcribe(str(audio), vad_filter=True)
        segments, previous_start = [], -1.0
        for segment in detected:
            start, end = float(segment.start), float(segment.end)
            if (not math.isfinite(start) or not math.isfinite(end) or start < 0
                    or start < previous_start or end <= start or end > duration + 0.001):
                raise ValueError()
            previous_start = start
            text = " ".join(segment.text.split())
            if text:
                segments.append({"id": "s%03d" % (len(segments) + 1), "start": start,
                                 "end": end, "text": text, "kind": "asr"})
        return segments
    except Exception:
        raise RuntimeError("本地转写失败；请检查 faster-whisper、模型缓存和音频质量。") from None


def prepare(video, out_dir, subtitles=None, interval=10, max_frames=24, at=None,
            transcribe=False, model="base"):
    video = Path(video).resolve()
    if not video.is_file():
        raise ValueError("本地视频不存在或不是文件。")
    out_dir = empty_output(out_dir)
    if transcribe and subtitles is None and importlib.util.find_spec("faster_whisper") is None:
        raise RuntimeError("缺少可选依赖 faster-whisper；请显式安装后重试，脚本不会自动安装。")
    for name in ("ffmpeg", "ffprobe"):
        require_tool(name)
    if importlib.util.find_spec("PIL") is None:
        raise RuntimeError("缺少依赖 Pillow；请先安装 Pillow。")
    duration, has_audio, frame_span = probe_video(video)
    times = frame_times(duration, interval, max_frames, at)
    segments = parse_subtitles(subtitles, duration) if subtitles is not None else []
    if transcribe and subtitles is None and not has_audio:
        raise ValueError("视频没有音轨，无法进行本地转写；请提供字幕。")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "frames").mkdir()
    audio_path = "audio.wav" if has_audio else None
    if has_audio:
        run_tool(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(video),
                  "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                  "-n", str(out_dir / audio_path)], "音频提取", timeout=600)
    if transcribe and subtitles is None:
        segments = transcribe_audio(out_dir / audio_path, duration, model)
    frames = []
    for index, seconds in enumerate(times, 1):
        identifier = "f%03d" % index
        path = "frames/" + identifier + ".jpg"
        seek_start = max(0.0, seconds - frame_span)
        window = seconds - seek_start
        # 取该时刻仍在显示的最后一帧；输入端 -t 限制解码窗口，保留完整画面。
        run_tool(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", str(seek_start),
                  "-t", str(window + 0.1), "-i", str(video), "-map", "0:v:0", "-vf",
                  "select=lte(t\\,%.9f)" % window, "-vsync", "0", "-update", "1", "-q:v", "2", "-n",
                  str(out_dir / path)], "原始视频取帧")
        if not (out_dir / path).is_file():
            raise RuntimeError("指定时间点无可解码画面；请换一个视频内的时间点。")
        frames.append({"id": identifier, "time": seconds, "path": path})
    status = segments[0]["kind"] if segments else "missing"
    evidence = {"source": {"kind": "local_video", "filename": video.name, "duration_seconds": duration},
                "segments": segments, "frames": frames, "audio_path": audio_path,
                "transcript_status": status}
    contact_sheet(out_dir, frames)
    (out_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    transcript = ["# 视频文字证据", "", "transcript_status: " + status, ""]
    transcript.extend("- [%s — %s] (%s) %s" % (format_time(s["start"]), format_time(s["end"]),
                       s["kind"], s.get("raw_text", s["text"])) for s in segments)
    if not segments:
        transcript.append("没有可用字幕或转写；请人工听看视频，不能据此编造菜谱信息。")
    (out_dir / "transcript.md").write_text("\n".join(transcript) + "\n", encoding="utf-8")
    return {"evidence": "evidence.json", "transcript": "transcript.md",
            "contact_sheet": "contact-sheet.jpg", "frames": len(frames),
            "audio_path": audio_path, "transcript_status": status}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("命令参数无效；请使用 --help 查看用法。")


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="检查依赖，输出 JSON")
    downloader = commands.add_parser("fetch", help="下载单个公开视频及独立字幕，不读取浏览器会话")
    downloader.add_argument("url")
    downloader.add_argument("--out-dir", required=True, type=Path)
    preparer = commands.add_parser("prepare", help="从本地视频准备原始证据，不覆盖已有文件")
    preparer.add_argument("video", type=Path)
    preparer.add_argument("--out-dir", required=True, type=Path)
    preparer.add_argument("--subtitles", type=Path)
    preparer.add_argument("--interval", type=float, default=10)
    preparer.add_argument("--max-frames", type=int, default=24)
    preparer.add_argument("--at", action="append", type=float, help="仅提取指定时间点，可重复指定")
    preparer.add_argument("--transcribe", action="store_true",
                          help="无字幕时使用 faster-whisper 本地转写；未缓存模型会下载")
    preparer.add_argument("--model", default="base", help="faster-whisper 模型名或本地模型目录")
    try:
        args = vars(parser.parse_args(argv))
        command = args.pop("command")
        result = {"check": check, "fetch": fetch, "prepare": prepare}[command](**args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
    except (OSError, UnicodeError, json.JSONDecodeError):
        print('{"error": "文件或元数据读取失败；请检查格式和访问权限。"}', file=sys.stderr)
    return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
