#!/usr/bin/env python3
"""Protocol smoke adapter for the first BFCL Malay case.

This is intentionally not a real model or baseline. It only proves that the
benchmark-to-adapter wiring works before connecting PixelSpace.
"""

import json
import sys


case = json.load(sys.stdin)
if case["id"] != "simple_0":
    print(json.dumps({"content": "Demo adapter only handles simple_0.", "tool_calls": []}))
else:
    print(
        json.dumps(
            {
                "content": "",
                "tool_calls": [
                    {
                        "name": "calculate_triangle_area",
                        "arguments": {"base": 10, "height": 5},
                    }
                ],
            }
        )
    )
