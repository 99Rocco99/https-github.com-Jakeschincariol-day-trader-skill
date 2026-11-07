import importlib.util
import io
import json
import os
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer

from _load import ROOT

PATH = os.path.join(ROOT, "plugins", "freellm", "skills", "freellm", "freellm.py")
spec = importlib.util.spec_from_file_location("freellm_tool", PATH)
freellm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freellm)


class Fake(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply(200, {"data": [{"id": "gemini-2.5-flash"}, {"id": "llama-3.3-70b-versatile"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append((self.path, self.headers.get("Authorization"), body))
        if self.headers.get("Authorization") != "Bearer good":
            return self.reply(401, {"error": "bad key"})
        self.reply(200, {"model": "gemini-2.5-flash",
                         "choices": [{"message": {"role": "assistant", "content": "hi there"}}]})


class FreeLLM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/v1" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Fake.seen = []
        self.env = dict(os.environ)
        os.environ["FREELLM_BASE_URL"] = self.base
        os.environ["FREELLM_API_KEY"] = "good"
        os.environ.pop("FREELLM_MODEL", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = freellm.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_ask_sends_auto_model_with_bearer_key(self):
        code, out, err = self.run_cli("ask", "hello", "--system", "be brief")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "hi there")
        self.assertIn("gemini-2.5-flash", err)
        path, auth, body = Fake.seen[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(auth, "Bearer good")
        self.assertEqual(body["model"], "auto")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "be brief"})

    def test_models_lists_ids(self):
        code, out, _ = self.run_cli("models")
        self.assertEqual(code, 0)
        self.assertEqual(out.split(), ["gemini-2.5-flash", "llama-3.3-70b-versatile"])

    def test_bad_key_is_explained(self):
        os.environ["FREELLM_API_KEY"] = "wrong"
        code, _, err = self.run_cli("ask", "hello")
        self.assertEqual(code, 1)
        self.assertIn("FREELLM_API_KEY", err)

    def test_server_down_is_explained(self):
        os.environ["FREELLM_BASE_URL"] = "http://127.0.0.1:1/v1"
        code, _, err = self.run_cli("ping")
        self.assertEqual(code, 1)
        self.assertIn("Is the server running?", err)

    def test_files_are_included(self):
        msgs = freellm.build_messages("sum it", files=[os.path.join(ROOT, "LICENSE")])
        self.assertIn("MIT", msgs[-1]["content"])
        self.assertTrue(msgs[-1]["content"].endswith("sum it"))

    def test_marketplace_lists_the_plugin(self):
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        entry = [p for p in market["plugins"] if p["name"] == "freellm"][0]
        self.assertEqual(entry["source"], "./plugins/freellm")
        manifest = os.path.join(ROOT, "plugins", "freellm", ".claude-plugin", "plugin.json")
        with open(manifest) as fh:
            self.assertEqual(json.load(fh)["name"], "freellm")


if __name__ == "__main__":
    unittest.main()
