#!/usr/bin/env python3
"""Talk to a FreeLLM API server (github.com/tashfeenahmed/freellmapi).

Plain Python 3.8+, standard library only. FreeLLM API speaks the OpenAI
format, so this sends /chat/completions and /models requests to it.

Settings (environment variables):
  FREELLM_API_KEY   the unified key from the FreeLLM dashboard's Keys page
  FREELLM_BASE_URL  default http://localhost:3001/v1
  FREELLM_MODEL     default "auto" (the router picks); also auto:fast,
                    auto:smart, auto:cheap, auto:reliable or a model id

Usage:
  freellm.py ping
  freellm.py models
  freellm.py ask [--model M] [--system TEXT] [--file PATH ...] [--max-tokens N] PROMPT
  (PROMPT "-" reads the prompt from stdin)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:3001/v1"
MAX_FILE_CHARS = 200000


class FreeLLMError(Exception):
    pass


def settings():
    base = (os.environ.get("FREELLM_BASE_URL") or DEFAULT_BASE).rstrip("/")
    key = os.environ.get("FREELLM_API_KEY", "")
    model = os.environ.get("FREELLM_MODEL") or "auto"
    return base, key, model


def request(method, url, key, body=None, timeout=180):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "freellm-claude-plugin/1.0")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code in (401, 403):
            raise FreeLLMError(
                "FreeLLM API refused the key (HTTP %d). Set FREELLM_API_KEY to the unified "
                "key from the dashboard's Keys page. Server said: %s" % (e.code, detail))
        raise FreeLLMError("FreeLLM API returned HTTP %d: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise FreeLLMError(
            "Could not reach FreeLLM API at %s (%s). Is the server running? Start it with "
            "Docker or `npm run dev` in the freellmapi folder, or set FREELLM_BASE_URL."
            % (url, e.reason))
    except ValueError:
        raise FreeLLMError("FreeLLM API sent a reply that is not JSON (from %s)." % url)


def list_models(base, key):
    reply = request("GET", base + "/models?available=true", key, timeout=30)
    return [m.get("id") for m in reply.get("data", []) if m.get("id")]


def build_messages(prompt, system=None, files=()):
    parts = []
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + "\n[... cut at %d characters]" % MAX_FILE_CHARS
        parts.append("File: %s\n```\n%s\n```" % (path, text))
    parts.append(prompt)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


def ask(base, key, model, messages, max_tokens=None):
    body = {"model": model, "messages": messages}
    if max_tokens:
        body["max_tokens"] = max_tokens
    reply = request("POST", base + "/chat/completions", key, body)
    choices = reply.get("choices") or []
    if not choices:
        raise FreeLLMError("FreeLLM API replied with no answer: %s" % json.dumps(reply)[:500])
    content = (choices[0].get("message") or {}).get("content") or ""
    return content, reply.get("model") or model


def main(argv=None):
    p = argparse.ArgumentParser(description="Ask the models behind a FreeLLM API server.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("ping", help="check the server is up and the key works")
    sub.add_parser("models", help="list the models the server can use right now")
    a = sub.add_parser("ask", help="send a prompt and print the answer")
    a.add_argument("prompt", help='the prompt, or "-" to read it from stdin')
    a.add_argument("--model", help="model id or auto:<mode> (default FREELLM_MODEL or auto)")
    a.add_argument("--system", help="system prompt")
    a.add_argument("--file", action="append", default=[], help="include a text file (repeatable)")
    a.add_argument("--max-tokens", type=int)
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 2

    base, key, model = settings()
    try:
        if args.cmd == "ping":
            ids = list_models(base, key)
            print("FreeLLM API is up at %s with %d model(s) available." % (base, len(ids)))
            if not key:
                print("Note: FREELLM_API_KEY is not set; chat requests will likely be refused.")
        elif args.cmd == "models":
            for mid in list_models(base, key):
                print(mid)
        else:
            prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
            messages = build_messages(prompt, args.system, args.file)
            text, used = ask(base, key, args.model or model, messages, args.max_tokens)
            print(text)
            sys.stderr.write("[freellm: answered by %s]\n" % used)
    except (FreeLLMError, OSError) as e:
        sys.stderr.write("freellm: %s\n" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
