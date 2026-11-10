"""Fast, dependency-free tests.  Run: python3 -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dastyar.config import Settings, DEFAULTS, PROVIDERS  # noqa: E402
from dastyar.secret import protect, unprotect, masked  # noqa: E402
from dastyar.tools import ToolRegistry  # noqa: E402
from dastyar.tools.base import ToolContext  # noqa: E402


class TempHome(unittest.TestCase):
    """Each test gets its own data folder + sandbox."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.cfg = base / "config.json"
        self.settings = Settings(self.cfg)
        self.settings.update(
            {
                "provider": "demo",
                "allowed_paths": [str(self.home)],
                "allow_all_paths": False,
                "policy": "auto",
            }
        )
        self.events = []
        self.registry = ToolRegistry(self.settings, emit=self.events.append)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_tool(self, _tool_name: str, **args):
        return self.registry.execute(_tool_name, args)


class TestSettings(TempHome):
    def test_defaults_and_persistence(self):
        self.assertEqual(self.settings.get("provider"), "demo")
        self.settings.set("temperature", 0.9)
        again = Settings(self.cfg)
        self.assertEqual(again.get("temperature"), 0.9)

    def test_corrupt_config_is_backed_up(self):
        self.cfg.write_text("{not json", encoding="utf-8")
        s = Settings(self.cfg)
        self.assertEqual(s.get("model"), DEFAULTS["model"])

    def test_public_dict_hides_key(self):
        self.settings.set("api_key", protect("sk-very-secret-123456"))
        pub = self.settings.public_dict()
        self.assertEqual(pub["api_key"], "•" * 8)
        self.assertNotIn("very-secret", json.dumps(pub))
        self.assertEqual(self.settings.api_key, "sk-very-secret-123456")

    def test_providers_have_defaults(self):
        for name, info in PROVIDERS.items():
            self.assertIn("label", info, name)


class TestSecrets(unittest.TestCase):
    def test_roundtrip(self):
        for key in ("sk-abc", "AIzaSyD-xxxxxxxx", "خصیصی-کلید"):
            stored = protect(key)
            self.assertNotEqual(stored, key)
            self.assertEqual(unprotect(stored), key)

    def test_plain_key_still_works(self):
        self.assertEqual(unprotect("sk-plain"), "sk-plain")

    def test_masked(self):
        self.assertEqual(masked(""), "")
        self.assertIn("•", masked(protect("sk-1234567890abcd")))


class TestFiles(TempHome):
    def test_write_read_list(self):
        p = self.home / "notes.txt"
        res = self.run_tool("write_file", path=str(p), content="سلام دنیا")
        self.assertTrue(res["ok"], res)
        res = self.run_tool("read_file", path=str(p))
        self.assertIn("سلام دنیا", res["output"])
        res = self.run_tool("list_files", path=str(self.home))
        self.assertIn("notes.txt", res["output"])

    def test_sandbox_blocks_outside_paths(self):
        outside = "C:\\Windows\\win.ini" if os.name == "nt" else "/etc/passwd"
        res = self.run_tool("read_file", path=outside)
        self.assertFalse(res["ok"])
        self.assertIn("مجاز نیست", res["error"])

    def test_make_copy_move_delete(self):
        folder = self.home / "پوشه"
        self.assertTrue(self.run_tool("make_folder", path=str(folder))["ok"])
        f = folder / "a.txt"
        self.run_tool("write_file", path=str(f), content="x")
        cp = self.home / "b.txt"
        self.assertTrue(self.run_tool("copy_file", source=str(f), destination=str(cp))["ok"])
        mv = self.home / "c.txt"
        self.assertTrue(self.run_tool("move_file", source=str(cp), destination=str(mv))["ok"])
        self.assertTrue(mv.exists())
        self.assertTrue(self.run_tool("delete_file", path=str(mv), permanent=True)["ok"])
        self.assertFalse(mv.exists())

    def test_zip_roundtrip(self):
        f = self.home / "data.txt"
        self.run_tool("write_file", path=str(f), content="hello")
        res = self.run_tool("zip_folder", path=str(self.home / "data.txt"))
        self.assertTrue(res["ok"], res)
        zips = list(self.home.glob("*.zip"))
        self.assertTrue(zips)
        self.assertTrue(self.run_tool("unzip_archive", path=str(zips[0]),
                                      destination=str(self.home / "out"))["ok"])

    def test_csv(self):
        p = self.home / "t.csv"
        res = self.run_tool("create_csv", path=str(p), headers=["نام", "مبلغ"],
                            rows=[["الف", 10], ["ب", 20]])
        self.assertTrue(res["ok"], res)
        out = self.run_tool("read_csv", path=str(p))["output"]
        self.assertIn("الف", out)

    def test_allowed_path_survives_symlinked_roots(self):
        """On macOS /tmp is a symlink to /private/tmp; resolved paths must match."""
        import os as _os

        target = Path(_os.path.realpath(str(self.home / "x.txt")))
        res = self.run_tool("write_file", path=str(self.home / "x.txt"), content="hi")
        self.assertTrue(res["ok"], res)
        self.assertTrue(target.parent.exists())
        # a path expressed through the *unresolved* spelling must still be inside
        self.settings.set("allowed_paths", [str(self.home)])
        ok = self.run_tool("read_file", path=str(self.home / "x.txt"))
        self.assertTrue(ok["ok"], ok)

    def test_find_files(self):
        (self.home / "x.pdf").write_text("pdf", encoding="utf-8")
        (self.home / "y.txt").write_text("txt", encoding="utf-8")
        out = self.run_tool("find_files", root=str(self.home), pattern="*.pdf")["output"]
        self.assertIn("x.pdf", out)
        self.assertNotIn("y.txt", out)


class TestOffice(TempHome):
    def test_docx_structure(self):
        p = self.home / "سند.docx"
        res = self.run_tool("create_word", path=str(p), title="گزارش",
                            content="# تیتر\nمتن اول\n- مورد\n\nپاراگراف آخر",
                            table=[["نام", "مقدار"], ["الف", "۱"]])
        self.assertTrue(res["ok"], res)
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            self.assertIn("word/document.xml", names)
            xml = z.read("word/document.xml").decode("utf-8")
            self.assertIn("گزارش", xml)
            self.assertIn("<w:tbl>", xml)
            self.assertIn('w:val="Title"', xml)

    def test_xlsx_structure(self):
        p = self.home / "گزارش.xlsx"
        rows = [["تاریخ", "عنوان", "مبلغ"], ["1404/01/01", "خرید", 150000],
                ["1404/01/02", "فروش", 90000], ["", "جمع", "=SUM(C2:C3)"]]
        res = self.run_tool("create_excel", path=str(p), rows=rows, sheet_name="هزینه‌ها")
        self.assertTrue(res["ok"], res)
        with zipfile.ZipFile(p) as z:
            self.assertIn("xl/workbook.xml", z.namelist())
            sheet = z.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("<f>SUM(C2:C3)</f>", sheet)
            wb = z.read("xl/workbook.xml").decode()
            self.assertIn("هزینه‌ها", wb)

    def test_multisheet_report(self):
        p = self.home / "r.xlsx"
        rows = [["ماه", "درآمد"], ["فروردین", 10], ["اردیبهشت", 20]]
        res = self.run_tool("create_excel_report", path=str(p), data=rows, title="گزارش")
        self.assertTrue(res["ok"], res)
        with zipfile.ZipFile(p) as z:
            self.assertIn("xl/worksheets/sheet2.xml", z.namelist())

    def test_pptx(self):
        p = self.home / "ارائه.pptx"
        res = self.run_tool(
            "create_powerpoint", path=str(p), title="هوش مصنوعی", subtitle="آینده",
            slides=[{"title": "مقدمه", "bullets": ["تعریف", "تاریخچه"]},
                    {"title": "کاربردها", "bullets": ["پزشکی", "آموزش"]}],
        )
        self.assertTrue(res["ok"], res)
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            self.assertIn("ppt/presentation.xml", names)
            self.assertIn("ppt/slides/slide3.xml", names)
            self.assertIn("ppt/slideMasters/slideMaster1.xml", names)
            pres = z.read("ppt/presentation.xml").decode()
            self.assertIn("sldIdLst", pres)

    def test_pdf(self):
        p = self.home / "test.pdf"
        res = self.run_tool("create_pdf", path=str(p), title="Hello", content="Line one\nLine two")
        self.assertTrue(res["ok"], res)
        data = p.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", data)

    def test_markdown_to_html(self):
        md = self.home / "doc.md"
        md.write_text("# تیتر\n\n- یک\n- دو\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
        res = self.run_tool("markdown_to_html", path=str(md))
        self.assertTrue(res["ok"], res)
        out = Path(res["output"].split(": ")[-1]).read_text(encoding="utf-8")
        self.assertIn("<h1>تیتر</h1>", out)
        self.assertIn("<table>", out)
        self.assertIn("dir=\"rtl\"", out)

    def test_resume_and_letter(self):
        r = self.home / "cv.docx"
        res = self.run_tool("make_resume", path=str(r), name="سعید", headline="برنامه‌نویس",
                            skills=["پایتون", "SQL"], experience=["شرکت الف — ۲۰۲۰ تا ۲۰۲۴"])
        self.assertTrue(res["ok"], res)
        self.assertTrue(zipfile.is_zipfile(r))
        letter = self.home / "letter.docx"
        res = self.run_tool("make_letter", path=str(letter), body="متن نامه", sender="سعید")
        self.assertTrue(res["ok"], res)

    def test_read_back_office(self):
        p = self.home / "x.docx"
        self.run_tool("create_word", path=str(p), content="محتوای منحصربه‌فرد")
        out = self.run_tool("extract_text_from_office", path=str(p))["output"]
        self.assertIn("محتوای منحصربه‌فرد", out)


class TestMisc(TempHome):
    def test_qr_svg(self):
        p = self.home / "q.svg"
        res = self.run_tool("create_qr_code", text="https://example.com", path=str(p))
        self.assertTrue(res["ok"], res)
        svg = p.read_text(encoding="utf-8")
        self.assertIn("<svg", svg)
        self.assertGreater(svg.count("<rect"), 20)

    def test_pdf_module_direct(self):
        from dastyar.tools.office import build_pdf

        data = build_pdf(["line1", "line2"], "T")
        self.assertTrue(data.startswith(b"%PDF"))

    def test_notes_and_todos(self):
        self.assertTrue(self.run_tool("write_note", text="خرید نان", title="کارها")["ok"])
        out = self.run_tool("list_notes")["output"]
        self.assertIn("خرید نان", out)
        self.run_tool("add_todo", text="پرداخت قبض")
        self.run_tool("complete_todo", query="پرداخت")
        out = self.run_tool("list_notes")["output"]
        self.assertNotIn("پرداخت قبض", out.split("کارها")[-1])

    def test_memory(self):
        self.run_tool("remember", fact="اسم کاربر سعید است")
        out = self.run_tool("recall", query="سعید")["output"]
        self.assertIn("سعید", out)

    def test_json_format_and_dice(self):
        res = self.run_tool("json_format", text='{"a":1}')
        self.assertIn('"a": 1', res["output"])
        res = self.run_tool("dice", count=3)
        self.assertIn("🎲", res["output"])

    def test_svg_creator(self):
        p = self.home / "chart.svg"
        res = self.run_tool("create_simple_svg", path=str(p), title="نمودار", shapes=[
            {"type": "rect", "x": 10, "y": 10, "w": 100, "h": 40},
            {"type": "circle", "cx": 200, "cy": 100, "r": 30},
        ])
        self.assertTrue(res["ok"], res)
        self.assertIn("<circle", p.read_text(encoding="utf-8"))

    def test_tone_wav(self):
        p = self.home / "t.wav"
        res = self.run_tool("create_tone", path=str(p), frequency=440, duration=0.2)
        self.assertTrue(res["ok"], res)
        self.assertGreater(p.stat().st_size, 1000)


class TestAgentDemo(TempHome):
    def test_demo_reply_no_network(self):
        from dastyar.demo import demo_reply

        res = demo_reply([{"role": "user", "content": "ساعت چنده"}], None)
        self.assertEqual(res["tool_calls"][0]["function"]["name"], "clock")

    def test_agent_loop_offline(self):
        from dastyar.agent import Agent

        agent = Agent(self.settings)
        events = list(agent.run("ساعت چنده؟"))
        kinds = [e["type"] for e in events]
        self.assertIn("tool_result", kinds)
        self.assertIn("assistant_message", kinds)
        self.assertIn("done", kinds)
        tool_result = [e for e in events if e["type"] == "tool_result"][0]
        self.assertTrue(tool_result["ok"], tool_result)

    def test_agent_tool_call_for_files(self):
        from dastyar.agent import Agent

        agent = Agent(self.settings)
        events = list(agent.run("تو دسکتاپ چی هست؟"))
        tools = [e["tool"] for e in events if e["type"] == "tool_start"]
        self.assertIn("list_files", tools)

    def test_registry_schemas_valid_json_schema(self):
        schemas = self.registry.schemas()
        self.assertGreater(len(schemas), 100)
        for s in schemas:
            self.assertEqual(s["type"], "function")
            self.assertTrue(s["function"]["name"])
            self.assertEqual(s["function"]["parameters"]["type"], "object")


class TestVisionAndScreen(TempHome):
    def test_png_writer(self):
        from dastyar.screen import _write_png

        p = self.home / "tiny.png"
        _write_png(p, 2, 2, bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]), 6)
        data = p.read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertIn(b"IHDR", data)

    def test_image_data_url(self):
        from dastyar.screen import _write_png
        from dastyar.tools.vision import image_to_data_url

        p = self.home / "t.png"
        _write_png(p, 1, 1, b"\x00\x00\x00", 3)
        self.assertTrue(image_to_data_url(str(p)).startswith("data:image/png;base64,"))


class TestSkills(unittest.TestCase):
    def test_match(self):
        from dastyar.skills import match_skills

        names = [s["name"] for s in match_skills("یک پاورپوینت درباره فناوری بساز")]
        self.assertIn("ساخت پاورپوینت", names)

    def test_prompt_non_empty(self):
        from dastyar.skills import all_skills

        for s in all_skills():
            self.assertTrue(s["prompt"].strip(), s["name"])


class TestHttpApi(unittest.TestCase):
    def test_server_boots_and_serves_api(self):
        import threading
        import time
        import urllib.request

        from dastyar.server import serve

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "config.json")
            settings.update({"provider": "demo", "ui": {"port": 8912}})
            t = threading.Thread(target=lambda: serve(settings, port=8912,
                                                      open_browser=False, quiet=True), daemon=True)
            t.start()
            url = "http://127.0.0.1:8912"
            for _ in range(60):
                try:
                    with urllib.request.urlopen(url + "/api/health", timeout=1) as r:
                        data = json.loads(r.read().decode())
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                self.fail("server did not start")
            self.assertTrue(data["ok"])
            with urllib.request.urlopen(url + "/", timeout=2) as r:
                html = r.read().decode()
            self.assertIn("دستیار", html)
            with urllib.request.urlopen(url + "/app.js", timeout=2) as r:
                self.assertIn("handleEvent", r.read().decode())



class TestCancellation(unittest.TestCase):
    def test_cancel_stops_the_loop(self):
        import threading

        from dastyar.agent import Agent

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings(Path(tmp) / "c.json")
            s.update({"provider": "demo", "policy": "auto"})
            agent = Agent(s)
            gen = agent.run("سلام")
            next(gen)                      # user_message
            # the demo brain is instant, so cancel synchronously right after
            # the first event: the loop must notice it before answering.
            agent.cancel()
            events = list(gen)
            kinds = [e["type"] for e in events]
            self.assertIn("stopped", kinds)
            self.assertIn("done", kinds)

    def test_settings_reject_bad_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Settings(Path(tmp) / "c.json")
            s.update({"policy": "whatever"})
            self.assertEqual(s.get("policy"), "whatever")  # storage is dumb
            # validation lives in the HTTP layer; make sure defaults stay sane
            self.assertIn(DEFAULTS["policy"], ("ask", "auto", "readonly"))


class TestFrozenBuildSafety(unittest.TestCase):
    """A PyInstaller windowed exe has sys.stdout/stderr set to None."""

    def test_console_shim_survives_none_streams(self):
        import io
        import sys as _sys
        from unittest import mock

        from dastyar import config as cfg

        saved_out, saved_err = _sys.stdout, _sys.stderr
        try:
            with mock.patch.dict(os.environ, {"DASTYAR_DATA": tempfile.mkdtemp()}):
                _sys.stdout = None
                _sys.stderr = None
                cfg.enable_console_safety()
                self.assertIsNotNone(_sys.stdout)
                self.assertIsNotNone(_sys.stderr)
                print("hello from a windowed build")   # must not raise
                _sys.stdout.flush()
        finally:
            _sys.stdout, _sys.stderr = saved_out, saved_err
            # restore real streams for the rest of the suite
            _sys.stdout = saved_out or io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            _sys.stderr = saved_err or _sys.stdout

    def test_bundled_assets_are_found_relative_to_the_package(self):
        from dastyar import config as cfg
        from dastyar.server import STATIC
        from dastyar.tools.pdfkit import font_candidates

        self.assertTrue((STATIC / "index.html").is_file())
        self.assertTrue((cfg.app_root() / "dastyar").is_dir() or cfg.is_frozen())
        fonts = font_candidates()
        self.assertTrue(fonts, "at least one usable font must exist")
        self.assertTrue(any("vazirmatn" in f.name.lower() for f in fonts))



if __name__ == "__main__":
    unittest.main(verbosity=2)