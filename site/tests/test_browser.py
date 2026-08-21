from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
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
            answers_path = output / "data" / "answers" / "chatable.json"
            answers = json.loads(answers_path.read_text(encoding="utf-8"))
            first_answer = answers["cases"][0]["answers"][0]
            first_answer["content"] += (
                "\n\n4. Langkah empat\n5. Langkah lima"
                "\n\n*Nota:* kekalkan x_1 dan papar \\*asterisk literal\\*."
                "\n\n<img src=x onerror=window.hostileHtmlRan=true>"
                "\n\n[Selamat](https://example.com/path) "
                "[JavaScript](javascript:window.hostileLinkRan=true) "
                "[Data](data:text/html,hostile)"
            )
            expected_raw_markdown = first_answer["content"]
            answers_path.write_text(
                json.dumps(answers, ensure_ascii=False),
                encoding="utf-8",
            )

            inspection_script = f"""
            <script>
              const expectedRawMarkdown = {json.dumps(expected_raw_markdown)};
              const inspectRenderedAnswer = window.setInterval(() => {{
                const answer = document.querySelector(".model-answer");
                const raw = answer?.querySelector(".answer-raw");
                if (!raw) return;
                window.clearInterval(inspectRenderedAnswer);
                raw.open = true;
                window.setTimeout(() => {{
                  const rendered = answer.querySelector(".answer-copy");
                  const links = Array.from(rendered.querySelectorAll("a"));
                  document.body.dataset.rawMarkdownExact = String(
                    raw.querySelector("pre")?.textContent === expectedRawMarkdown
                  );
                  document.body.dataset.hostileHtmlInert = String(
                    !rendered.querySelector("img") && !window.hostileHtmlRan
                  );
                  document.body.dataset.unsafeLinksInert = String(
                    links.length === 1
                    && links[0].href === "https://example.com/path"
                    && !window.hostileLinkRan
                  );
                }}, 0);
              }}, 25);
            </script>
            """
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
                self.assertEqual(
                    rendered.count("Luas bagi sebuah segi tiga dikira dengan formula"),
                    1,
                )
                self.assertIn("Luas segitiga dihitung dengan rumus", rendered)
                self.assertIn('<div class="answer-copy markdown-body">', rendered)
                self.assertIn("<strong>25 unit persegi</strong>", rendered)
                self.assertIn(
                    '<h5 class="markdown-heading markdown-heading-3">Persamaan Kuadratik</h5>',
                    rendered,
                )
                self.assertIn(
                    '<pre class="markdown-code-block"><code class="language-python">',
                    rendered,
                )
                self.assertIn("Raw Markdown", rendered)
                self.assertIn('<ol start="4">', rendered)
                self.assertIn("<em>Nota:</em>", rendered)
                self.assertIn("*asterisk literal*", rendered)
                self.assertNotIn("<em>asterisk literal</em>", rendered)
                self.assertIn("x_1", rendered)
                self.assertIn("&lt;img src=x onerror=window.hostileHtmlRan=true&gt;", rendered)
                self.assertIn('<a href="https://example.com/path"', rendered)
                self.assertNotIn('<a href="javascript:', rendered)
                self.assertNotIn('<a href="data:', rendered)
                self.assertIn("&lt;/parameter&gt;", rendered)
                self.assertNotIn("<strong>&lt;/parameter&gt;</strong>", rendered)
                self.assertIn("200 of 200 cases", rendered)
                self.assertIn("Download JSON", rendered)
                self.assertNotIn("Loading benchmark results", rendered)
                self.assertNotIn("Loading model answers", rendered)

                # Serving-speed section renders from latency.json.
                self.assertIn("How fast it answers", rendered)
                self.assertIn("nemotron-3.5-lightning", rendered)
                self.assertIn("275 tok/s", rendered)
                self.assertNotIn("Loading latency results", rendered)

                index = output / "index.html"
                index.write_text(
                    index.read_text(encoding="utf-8").replace(
                        "</body>", f"{inspection_script}</body>", 1
                    ),
                    encoding="utf-8",
                )
                inspected = self.dump_page(
                    f"{base_url}/?category=multiple&answers=chatable",
                    temporary_path / "chrome-inspected-answer",
                )
                self.assertIn('data-raw-markdown-exact="true"', inspected)
                self.assertIn('data-hostile-html-inert="true"', inspected)
                self.assertIn('data-unsafe-links-inert="true"', inspected)

                (output / "data" / "answers" / "chatable.json").unlink()
                missing_answers = self.dump_page(
                    f"{base_url}/?answers=chatable",
                    temporary_path / "chrome-missing-answers",
                )
                self.assertIn("The raw model answers could not be loaded", missing_answers)
                self.assertIn("0 of 0 cases", missing_answers)
                self.assertIn("Unavailable", missing_answers)

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
