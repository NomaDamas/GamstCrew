import unittest
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


if __name__ == "__main__":
    unittest.main()
