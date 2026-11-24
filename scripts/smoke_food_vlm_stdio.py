"""Manual / smoke test: start food_vlm server and exercise it via stdio.

Usage:
    # mock mode (no API call)
    uv run python scripts/smoke_food_vlm_stdio.py

    # real Qwen-VL on a specific image
    uv run python scripts/smoke_food_vlm_stdio.py --real --image data/test_images/meal.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make the project importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(image: str, hint: str, real: bool) -> int:
    server_args = ["-m", "backend.app.mcp_servers.food_vlm.server"]
    if not real:
        server_args.append("--mock")

    params = StdioServerParameters(
        command=sys.executable,
        args=server_args,
        env=None,  # inherit (so DASHSCOPE_API_KEY is visible to the child)
    )

    mode = "real Qwen-VL" if real else "mock"
    print(f">>> spawning food_vlm server ({mode}) over stdio...")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(">>> initialized.")

            tools = await session.list_tools()
            print(f">>> list_tools: {[t.name for t in tools.tools]}")

            print(f">>> calling recognize_food(image={image!r}, hint={hint!r}) ...")
            result = await session.call_tool(
                "recognize_food", {"image": image, "hint": hint}
            )
            print("    isError =", result.isError)
            if result.structuredContent:
                sc = result.structuredContent
                print(f"    mode = {sc.get('mode')}")
                print(f"    image_quality = {sc.get('image_quality')}")
                print(f"    overall_confidence = {sc.get('overall_confidence')}")
                print(f"    total_kcal = {sc.get('total_kcal')}")
                print(f"    items: {[i['name'] for i in sc.get('items', [])]}")
                print(f"    notes = {sc.get('notes')}")
            for c in result.content:
                if hasattr(c, "text"):
                    parsed = json.loads(c.text) if c.text.strip().startswith("{") else None
                    if parsed:
                        print(json.dumps(parsed, ensure_ascii=False, indent=2))
                    else:
                        print("    [text]", c.text)
            print(">>> done.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="Use real Qwen-VL (requires DASHSCOPE_API_KEY).")
    parser.add_argument("--image", default="/tmp/fake.jpg",
                        help="Image path or URL.")
    parser.add_argument("--hint", default="lunch demo")
    args = parser.parse_args()
    return asyncio.run(run(args.image, args.hint, args.real))


if __name__ == "__main__":
    raise SystemExit(main())
