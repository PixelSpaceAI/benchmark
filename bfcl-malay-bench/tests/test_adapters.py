import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from pixel_bench.adapters import CommandAdapter, OpenAIAdapter, normalize_json_schema
from pixel_bench.models import Case


def make_case():
    return Case(
        id="simple_0",
        category="simple",
        messages=[{"role": "user", "content": "Kira lima faktorial."}],
        tools=[
            {
                "name": "math.factorial",
                "description": "Kira faktorial.",
                "parameters": {
                    "type": "dict",
                    "properties": {"number": {"type": "integer"}},
                },
            }
        ],
        ground_truth=[{"math.factorial": {"number": [5]}}],
        raw={"id": "simple_0"},
    )


class CommandAdapterTests(unittest.TestCase):
    def test_invokes_command_with_json_stdin(self):
        script = (
            "import json,sys; case=json.load(sys.stdin); "
            "print(json.dumps({'tool_calls':[{'name':case['tools'][0]['name'],"
            "'arguments':{'number':5}}]}))"
        )
        adapter = CommandAdapter([sys.executable, "-c", script], timeout=5)

        response = adapter.invoke(make_case())

        self.assertEqual(response.tool_calls[0]["name"], "math.factorial")
        self.assertEqual(response.tool_calls[0]["arguments"], {"number": 5})

    def test_surfaces_nonzero_exit(self):
        adapter = CommandAdapter(
            [sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(3)"],
            timeout=5,
        )

        with self.assertRaisesRegex(RuntimeError, "boom"):
            adapter.invoke(make_case())


class SchemaNormalizationTests(unittest.TestCase):
    def test_maps_bfcl_language_types_to_json_schema(self):
        schema = normalize_json_schema(
            {
                "type": "dict",
                "properties": {
                    "values": {"type": "tuple", "items": {"type": "long"}},
                    "metadata": {"type": "HashMap"},
                    "label": {"type": "char"},
                    "anything": {"type": "any"},
                },
            }
        )

        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["values"]["type"], "array")
        self.assertEqual(schema["properties"]["values"]["items"]["type"], "integer")
        self.assertEqual(schema["properties"]["metadata"]["type"], "object")
        self.assertEqual(schema["properties"]["label"]["type"], "string")
        self.assertNotIn("type", schema["properties"]["anything"])


class _Handler(BaseHTTPRequestHandler):
    request_payload = None

    def do_POST(self):
        length = int(self.headers["content-length"])
        type(self).request_payload = json.loads(self.rfile.read(length))
        response = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "math.factorial",
                                    "arguments": '{"number":5}',
                                }
                            }
                        ],
                    }
                }
            ]
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class OpenAIAdapterTests(unittest.TestCase):
    def test_calls_chat_completions_and_normalizes_bfcl_schema(self):
        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = OpenAIAdapter(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model="pixelspace-test",
                api_key="secret",
                timeout=5,
            )
            response = adapter.invoke(make_case())
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(response.tool_calls[0]["arguments"], {"number": 5})
        request = _Handler.request_payload
        self.assertEqual(request["model"], "pixelspace-test")
        self.assertEqual(request["tools"][0]["type"], "function")
        self.assertEqual(
            request["tools"][0]["function"]["parameters"]["type"], "object"
        )


if __name__ == "__main__":
    unittest.main()
