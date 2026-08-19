import unittest

from pixel_bench.normalize import normalize_response


class NormalizeResponseTests(unittest.TestCase):
    def test_normalizes_openai_tool_calls(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "math.factorial",
                                    "arguments": '{"number": 5}',
                                }
                            }
                        ],
                    }
                }
            ]
        }

        response = normalize_response(payload)

        self.assertEqual(response.content, "")
        self.assertEqual(
            response.tool_calls,
            [{"name": "math.factorial", "arguments": {"number": 5}}],
        )

    def test_normalizes_command_adapter_shape(self):
        response = normalize_response(
            {
                "content": "done",
                "tool_calls": [
                    {"name": "weather.get", "arguments": {"city": "Kuala Lumpur"}}
                ],
            }
        )

        self.assertEqual(response.content, "done")
        self.assertEqual(response.tool_calls[0]["name"], "weather.get")

    def test_normalizes_anthropic_tool_use_blocks(self):
        response = normalize_response(
            {
                "content": [
                    {"type": "text", "text": "Checking."},
                    {
                        "type": "tool_use",
                        "name": "weather.get",
                        "input": {"city": "Kuala Lumpur"},
                    },
                ]
            }
        )

        self.assertEqual(response.content, "Checking.")
        self.assertEqual(
            response.tool_calls,
            [{"name": "weather.get", "arguments": {"city": "Kuala Lumpur"}}],
        )

    def test_rejects_invalid_argument_json(self):
        with self.assertRaisesRegex(ValueError, "arguments"):
            normalize_response(
                {"tool_calls": [{"name": "broken", "arguments": "not-json"}]}
            )


if __name__ == "__main__":
    unittest.main()
