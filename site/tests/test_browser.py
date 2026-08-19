from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from test_build import REPOSITORY_ROOT, load_build_module


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class BrowserSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = next(
            (
                executable
                for name in ("google-chrome", "chromium", "chromium-browser")
                if (executable := shutil.which(name))
            ),
            None,
        )
        if cls.chrome is None:
            raise RuntimeError("Chrome or Chromium is required for the dashboard smoke test")

    def dump_page(self, url, user_data_directory):
        completed = subprocess.run(
            [
                self.chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--dump-dom",
                "--virtual-time-budget=3000",
                f"--user-data-dir={user_data_directory}",
                url,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=20,
        )
        return completed.stdout

    def test_built_dashboard_renders_data_category_and_error_state(self):
        build = load_build_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            output = temporary_path / "public"
            build.build_site(REPOSITORY_ROOT, output)
            handler = lambda *args, **kwargs: QuietHandler(
                *args, directory=str(output), **kwargs
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                rendered = self.dump_page(
                    f"{base_url}/?category=multiple&answers=chatable",
                    temporary_path / "chrome-success",
                )
                self.assertIn("76.54%", rendered)
                self.assertIn("ILMU Mini v3.3", rendered)
                self.assertIn("Multiple choices", rendered)
                self.assertIn("130 / 200", rendered)
                self.assertIn("Read every response", rendered)
                self.assertIn("chatable_0", rendered)
                self.assertIn("Luas bagi sebuah segi tiga dikira dengan formula", rendered)
                self.assertIn("Luas segitiga dihitung dengan rumus", rendered)
                self.assertIn(
                    '<pre class="answer-copy">\n&lt;/parameter&gt;',
                    rendered,
                )
                self.assertIn("200 of 200 cases", rendered)
                self.assertIn("Download JSON", rendered)
                self.assertNotIn("Loading benchmark results", rendered)
                self.assertNotIn("Loading model answers", rendered)

                (output / "data" / "answers" / "chatable.json").unlink()
                missing_answers = self.dump_page(
                    f"{base_url}/?answers=chatable",
                    temporary_path / "chrome-missing-answers",
                )
                self.assertIn("The raw model answers could not be loaded", missing_answers)
                self.assertIn("0 of 0 cases", missing_answers)
                self.assertIn("Unavailable", missing_answers)

                index = output / "index.html"
                index.write_text(
                    index.read_text(encoding="utf-8").replace(
                        './data/comparison.json', './data/missing.json', 1
                    ),
                    encoding="utf-8",
                )
                failed = self.dump_page(base_url, temporary_path / "chrome-failure")
                self.assertIn("The benchmark data could not be loaded", failed)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
