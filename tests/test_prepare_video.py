"""素材准备器的行为测试；测试素材全部在本地生成。"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_video.py"
TEMP_ROOT = ROOT / "tests" / ".tmp-prepare"


def temporary_directory():
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    result = tempfile.TemporaryDirectory(dir=str(TEMP_ROOT))
    Path(result.name).resolve().relative_to(ROOT.resolve())
    return result


class TestHelpers:
    def setUp(self):
        self.temp = temporary_directory()
        self.work = Path(self.temp.name)

    def tearDown(self):
        Path(self.temp.name).resolve().relative_to(ROOT.resolve())
        self.temp.cleanup()

    def module(self):
        self.assertTrue(SCRIPT.is_file(), "素材准备脚本尚未实现")
        spec = importlib.util.spec_from_file_location("prepare_video", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=90)

    def subtitles(self, text, name="captions.vtt"):
        target = self.work / name
        target.write_text(text, encoding="utf-8-sig")
        return target


class ScriptTests(TestHelpers, unittest.TestCase):
    def test_check_returns_dependency_booleans_without_machine_paths(self):
        result = self.cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data["dependencies"]["ffmpeg"], bool)
        self.assertIsInstance(data["dependencies"]["Pillow"], bool)
        self.assertIsInstance(data["dependencies"]["faster_whisper"], bool)
        self.assertNotIn(str(Path(sys.executable).parent), result.stdout)

    def test_srt_preserves_timestamps_and_removes_html(self):
        target = self.subtitles("1\n00:00:00,125 --> 00:00:01,250\n<b>切成小块</b> &amp; 拌匀\n",
                                "captions.srt")
        segments = self.module().parse_subtitles(target, 3)
        self.assertEqual(segments, [{"id": "s001", "start": 0.125, "end": 1.25,
                                     "text": "切成小块 & 拌匀", "kind": "subtitle"}])

    def test_vtt_rolling_captions_keep_each_new_word(self):
        target = self.subtitles(
            "WEBVTT\n\nNOTE metadata\nignored\n\n"
            "cue-a\n00:00.000 --> 00:02.000 align:start\n<c>Add <00:00.500>salt</c>\n\n"
            "00:01.000 --> 00:03.000\nAdd salt and pepper\n\n"
            "00:02.000 --> 00:04.000\nand pepper then stir\n\n"
            "00:03.000 --> 00:05.000\nand pepper then stir\n\n"
            "00:04.000 --> 00:06.000\nand pepper then stir slowly\n")
        segments = self.module().parse_subtitles(target, 7)
        self.assertEqual([s["text"] for s in segments],
                         ["Add salt", "and pepper", "then stir", "slowly"])
        self.assertEqual(segments[-1]["start"], 4.0)
        self.assertEqual(segments[-1]["end"], 6.0)

    def test_chinese_rolling_captions_preserve_added_characters(self):
        target = self.subtitles("WEBVTT\n\n00:00.000 --> 00:02.000\n放入葱姜\n\n"
                                "00:01.000 --> 00:03.000\n葱姜炒出香味\n")
        segments = self.module().parse_subtitles(target, 4)
        self.assertEqual([s["text"] for s in segments], ["放入葱姜", "炒出香味"])

    def test_rolling_caption_keeps_original_measurement_as_auditable_raw_text(self):
        target = self.subtitles("WEBVTT\n\n00:00.000 --> 00:02.000\n盐一勺\n\n"
                                "00:01.000 --> 00:03.000\n一勺生抽\n")
        segments = self.module().parse_subtitles(target, 4)
        self.assertEqual(segments[1]["text"], "生抽")
        self.assertEqual(segments[1].get("raw_text"), "一勺生抽")

    def test_words_after_a_real_pause_are_not_removed(self):
        target = self.subtitles("WEBVTT\n\n00:00.000 --> 00:01.000\n加盐\n\n"
                                "00:03.000 --> 00:04.000\n加盐调味\n")
        self.assertEqual([s["text"] for s in self.module().parse_subtitles(target, 5)],
                         ["加盐", "加盐调味"])

    def test_nonoverlapping_subtitle_sentences_keep_repeated_measurements(self):
        for name in ["captions.srt", "captions.vtt"]:
            with self.subTest(name=name):
                target = self.subtitles("00:00:00.000 --> 00:00:01.000\n盐一勺\n\n"
                                        "00:00:01.100 --> 00:00:02.000\n一勺生抽\n", name)
                self.assertEqual([s["text"] for s in self.module().parse_subtitles(target, 3)],
                                 ["盐一勺", "一勺生抽"])

    def test_subtitles_reject_bad_reversed_unordered_and_out_of_range_times(self):
        cases = ["00:00:00,100 --> 00:00:00,050", "00:00:00,000 --> 00:00:09,000",
                 "00:61:00,000 --> 00:61:01,000", "bad --> 00:00:01,000",
                 "00:00:02,000 --> 00:00:03,000\n先\n\n"
                 "00:00:01,000 --> 00:00:02,000"]
        module = self.module()
        for times in cases:
            with self.subTest(times=times):
                target = self.subtitles("1\n" + times + "\n拌匀\n", "captions.srt")
                with self.assertRaises(ValueError):
                    module.parse_subtitles(target, 4)

    def test_frame_cap_samples_across_the_video(self):
        self.assertEqual(self.module().frame_times(100, 10, 3, []), [0.0, 40.0, 90.0])

    def test_explicit_frames_are_sorted_unique_and_within_duration(self):
        module = self.module()
        self.assertEqual(module.frame_times(5, 10, 4, [4, 1, 1, 0]), [0.0, 1.0, 4.0])
        for points in [[5], [-1], [float("nan")]]:
            with self.subTest(points=points), self.assertRaises(ValueError):
                module.frame_times(5, 10, 4, points)
        with self.assertRaises(ValueError):
            module.frame_times(5, 0, 4, [])
        with self.assertRaises(ValueError):
            module.frame_times(5, 1, 0, [])

    def test_fetch_rejects_credentials_and_private_urls_without_echoing_them(self):
        for url in ["https://user:SECRET@example.com/video", "https://example.com/v?token=SECRET",
                    "https://example.com/v?Api_Key=SECRET", "file:///private/video.mp4",
                    "http://127.0.0.1/video", "http://localhost/video"]:
            with self.subTest(url=url):
                result = self.cli("fetch", url, "--out-dir", self.work / "download")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("URL", result.stderr)
                self.assertNotIn("SECRET", result.stdout + result.stderr)
                self.assertFalse((self.work / "download").exists())

    def test_fetch_keeps_safe_metadata_and_separate_subtitle_files(self):
        module = self.module()
        destination = self.work / "download"
        calls = []

        def downloader(command, **kwargs):
            calls.append(command)
            if "--skip-download" in command:
                (destination / "source.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")
            (destination / "source.mp4").write_bytes(b"video fixture")
            info = {"id": "fixture", "title": "番茄炒蛋", "duration": 2,
                    "extractor": "Generic", "webpage_url": "https://example.com/video",
                    "http_headers": {"Authorization": "SECRET"},
                    "formats": [{"url": "https://cdn.example/video?token=SECRET"}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(info), "")

        with patch.object(module.subprocess, "run", side_effect=downloader):
            result = module.fetch("https://example.com/video", destination)
        self.assertEqual(result["video_path"], "source.mp4")
        self.assertEqual(result["subtitle_paths"], ["source.en.vtt"])
        stored = (destination / "metadata.json").read_text(encoding="utf-8")
        self.assertIn("番茄炒蛋", stored)
        self.assertNotIn("SECRET", stored)
        self.assertEqual(len(calls), 2)
        for command in calls:
            for flag in ["--no-playlist", "--ignore-config", "--no-cookies"]:
                self.assertIn(flag, command)
            self.assertNotIn("--netrc", command)
            self.assertEqual(command[command.index("--retries") + 1], "0")
            if shutil.which("yt-dlp"):
                parsed = subprocess.run(command[:-2] + ["--help"], capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertIn("--no-write-subs", calls[0])
        self.assertIn("--skip-download", calls[1])

    def test_fetch_stops_after_first_failure_and_hides_downloader_logs(self):
        module = self.module()
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "", "url=password=SECRET")) as downloader:
            with self.assertRaisesRegex(RuntimeError, "下载") as failure:
                module.fetch("https://example.com/video", self.work / "failed")
        self.assertEqual(downloader.call_count, 1)
        self.assertNotIn("SECRET", str(failure.exception))

    def test_fetch_refuses_playlist_metadata_and_bounds_it_to_one_video(self):
        module = self.module()
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, json.dumps({"_type": "playlist", "entries": []}), "")) as downloader:
            with self.assertRaisesRegex(RuntimeError, "单个视频"):
                module.fetch("https://example.com/playlist", self.work / "playlist")
        self.assertEqual(downloader.call_count, 1)
        command = downloader.call_args.args[0]
        self.assertIn("--playlist-items", command)
        self.assertEqual(command[command.index("--playlist-items") + 1], "1")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
class RealVideoTests(TestHelpers, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = temporary_directory()
        cls.fixtures = Path(cls.fixture_temp.name)
        cls.silent = cls.fixtures / "silent.mp4"
        cls.voiced = cls.fixtures / "with-audio.mp4"
        commands = [
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=red:s=160x120:r=4:d=1", "-f", "lavfi", "-i",
             "color=c=blue:s=160x120:r=4:d=1", "-filter_complex",
             "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-c:v", "mpeg4",
             "-pix_fmt", "yuv420p", "-n", str(cls.silent)],
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=blue:s=160x120:r=4:d=2", "-f", "lavfi", "-i",
             "sine=frequency=400:sample_rate=16000:duration=2", "-c:v", "mpeg4",
             "-c:a", "aac", "-shortest", "-n", str(cls.voiced)]
        ]
        for command in commands:
            subprocess.run(command, check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        Path(cls.fixture_temp.name).resolve().relative_to(ROOT.resolve())
        cls.fixture_temp.cleanup()

    def test_prepare_silent_video_has_real_full_frames_and_missing_transcript(self):
        from PIL import Image
        output = self.work / "silent-evidence"
        result = self.cli("prepare", self.silent, "--out-dir", output, "--at", "0", "--at", "1.5")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(data["source"]["filename"], "silent.mp4")
        self.assertEqual(data["source"]["kind"], "local_video")
        self.assertAlmostEqual(data["source"]["duration_seconds"], 2.0, places=2)
        self.assertEqual(data["transcript_status"], "missing")
        self.assertEqual(data["segments"], [])
        self.assertIsNone(data["audio_path"])
        self.assertFalse((output / "audio.wav").exists())
        self.assertEqual([f["time"] for f in data["frames"]], [0.0, 1.5])
        images = []
        for frame in data["frames"]:
            self.assertFalse(Path(frame["path"]).is_absolute())
            with Image.open(output / frame["path"]) as img:
                self.assertEqual(img.size, (160, 120))
                images.append(img.getpixel((80, 60)))
        self.assertGreater(images[0][0], 200)
        self.assertLess(images[0][2], 30)
        self.assertGreater(images[1][2], 200)
        self.assertLess(images[1][0], 30)
        with Image.open(output / "contact-sheet.jpg") as sheet:
            self.assertGreaterEqual(sheet.width, 320)
        self.assertIn("missing", (output / "transcript.md").read_text(encoding="utf-8"))
        self.assertNotIn(str(self.fixtures), result.stdout + result.stderr)

    def test_prepare_extracts_mono_audio_and_timestamped_subtitle_transcript(self):
        subtitles = self.subtitles("1\n00:00:00,125 --> 00:00:01,250\n下锅翻炒\n", "captions.srt")
        output = self.work / "voiced-evidence"
        result = self.cli("prepare", self.voiced, "--out-dir", output,
                          "--subtitles", subtitles, "--interval", "1", "--max-frames", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(data["audio_path"], "audio.wav")
        self.assertEqual(data["transcript_status"], "subtitle")
        self.assertEqual(data["segments"][0]["text"], "下锅翻炒")
        with wave.open(str(output / "audio.wav")) as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getframerate(), 16000)
            self.assertGreater(audio.getnframes(), 16000)
        text = (output / "transcript.md").read_text(encoding="utf-8")
        self.assertIn("00:00:00.125", text)
        self.assertIn("00:00:01.250", text)
        self.assertIn("下锅翻炒", text)

    def test_prepare_can_capture_the_last_displayed_frame_before_video_end(self):
        from PIL import Image
        output = self.work / "last-frame"
        result = self.cli("prepare", self.silent, "--out-dir", output, "--at", "1.999")
        self.assertEqual(result.returncode, 0, result.stderr)
        with Image.open(output / "frames" / "f001.jpg") as image:
            self.assertGreater(image.getpixel((80, 60))[2], 200)

    def test_prepare_captures_current_frame_instead_of_a_future_scene(self):
        from PIL import Image
        output = self.work / "before-cut"
        result = self.cli("prepare", self.silent, "--out-dir", output, "--at", "0.999")
        self.assertEqual(result.returncode, 0, result.stderr)
        with Image.open(output / "frames" / "f001.jpg") as image:
            self.assertGreater(image.getpixel((80, 60))[0], 200)
            self.assertLess(image.getpixel((80, 60))[2], 30)

    def test_transcript_uses_full_original_rolling_caption_for_measurement_audit(self):
        subtitles = self.subtitles("WEBVTT\n\n00:00.000 --> 00:01.200\n盐一勺\n\n"
                                   "00:00.500 --> 00:01.800\n一勺生抽\n")
        output = self.work / "raw-captions"
        result = self.cli("prepare", self.silent, "--out-dir", output,
                          "--subtitles", subtitles, "--max-frames", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("一勺生抽", (output / "transcript.md").read_text(encoding="utf-8"))

    def test_prepare_refuses_nonempty_destination_without_changing_it(self):
        output = self.work / "existing"
        output.mkdir()
        marker = output / "important.txt"
        marker.write_text("keep", encoding="utf-8")
        result = self.cli("prepare", self.silent, "--out-dir", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("为空", result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(output.iterdir()), [marker])

    def test_prepare_rejects_out_of_duration_subtitles_before_writing(self):
        subtitles = self.subtitles("1\n00:00:00,000 --> 00:00:03,000\n超出时长\n", "bad.srt")
        output = self.work / "bad-evidence"
        result = self.cli("prepare", self.silent, "--out-dir", output, "--subtitles", subtitles)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("字幕", result.stderr)
        self.assertFalse(output.exists())

    def test_opt_in_transcription_missing_dependency_has_a_clear_message(self):
        module = self.module()
        output = self.work / "asr"
        with patch.object(module.importlib.util, "find_spec", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "faster.whisper"):
                module.prepare(self.voiced, output, transcribe=True)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
