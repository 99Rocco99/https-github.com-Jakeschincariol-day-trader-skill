---
name: freellm
description: >-
  Ask the free models behind the user's own FreeLLM API server
  (github.com/tashfeenahmed/freellmapi), an OpenAI-compatible router over
  free-tier LLM providers. Use for a second opinion from another model, bulk
  or cheap work (summaries, drafts, classifying many items, rewording), or
  when the user says "ask freellm", "use the free model", "ask another
  model", "get a second opinion", "run this through FreeLLM", "which free
  models do I have", or "is freellm working".
argument-hint: "[ping | models | ask <prompt>]"
---

# freellm

Sends a prompt to the user's FreeLLM API server and returns the answer.
FreeLLM API runs on the user's machine (default `http://localhost:3001`) and
routes each request to one of the free providers they added keys for.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/freellm.py" ping                       # server up? key set?
python3 "${CLAUDE_SKILL_DIR}/freellm.py" models                     # models usable right now
python3 "${CLAUDE_SKILL_DIR}/freellm.py" ask "Summarize this in 3 bullets" --file notes.md
python3 "${CLAUDE_SKILL_DIR}/freellm.py" ask "..." --model auto:fast --system "Answer briefly."
echo "long prompt" | python3 "${CLAUDE_SKILL_DIR}/freellm.py" ask -
```

The answer goes to stdout. The model that answered goes to stderr as
`[freellm: answered by <model>]`.

## Settings

| Variable | Default | What it is |
| --- | --- | --- |
| `FREELLM_API_KEY` | none | The unified key from the FreeLLM dashboard's Keys page |
| `FREELLM_BASE_URL` | `http://localhost:3001/v1` | Where the server is |
| `FREELLM_MODEL` | `auto` | `auto` lets the router pick; also `auto:fast`, `auto:smart`, `auto:cheap`, `auto:reliable`, or a model id from `models` |

## How to use it

1. If this is the first call in the session, run `ping`. If it says the
   server cannot be reached, tell the user to start FreeLLM API (Docker, or
   `npm run dev` in the freellmapi folder) and stop. If the key is refused,
   tell them to set `FREELLM_API_KEY` (for example in the `env` block of
   `~/.claude/settings.json`) and stop. Never ask them to paste the key into
   the chat.
2. Pass files with `--file` instead of pasting large text into the prompt.
   Each file is cut at 200,000 characters.
3. Show the user the answer and say which model gave it. Free models are
   weaker and less reliable than Claude: check anything factual or any code
   before relying on it, and say so when they disagree with you.
4. Do not send secrets, credentials or private data the user has not
   approved sending: the prompt leaves this machine for a third-party
   provider.
