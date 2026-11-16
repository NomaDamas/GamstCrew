import unittest
import asyncio
from gamstcrew.transport import JsonlUnixServer, jsonl_call


class Transport(unittest.IsolatedAsyncioTestCase):
    async def test_roundtrip_and_error_bound(self):
        async def handler(request):
            return {"id": request["id"], "ok": True}

        server = JsonlUnixServer(handler, max_line=1024)
        await server.start()
        try:
            self.assertEqual(
                await jsonl_call(server.path, {"id": 1}), {"id": 1, "ok": True}
            )
            response = await jsonl_call(server.path, {"data": "x" * 2000})
            self.assertIn("error", response)
        finally:
            await server.close()

    async def test_oversized_line_without_newline_is_rejected(self):
        async def handler(request):
            return {"ok": True}

        server = JsonlUnixServer(handler, max_line=32)
        await server.start()
        reader, writer = await asyncio.open_unix_connection(server.path, limit=1024)
        try:
            writer.write(b"x" * 33)
            await writer.drain()
            response = await reader.readuntil(b"\n")
            self.assertIn(b"line exceeds transport bound", response)
        finally:
            writer.close()
            await writer.wait_closed()
            await server.close()


if __name__ == "__main__":
    unittest.main()
