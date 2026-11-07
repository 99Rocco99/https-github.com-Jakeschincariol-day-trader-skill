# NOTES.md

Where things stand, kept current by Claude at the end of each task. Newest
first.

## In progress

Nothing.

## Next

- Merge branch `claude/great-knuth-djg72q` into `main` so new sessions pick
  up `CLAUDE.md` and this file (sessions start from `main`).

## Log

- 2026-11-07: Added `CLAUDE.md` (read by every session) and this file, plus
  a `.gitignore` for Python cache files.
- 2026-11-07: Talked about claude-mem (thedotmack/claude-mem), a memory
  plugin. It only remembers on the user's own computer, not in cloud
  sessions, so `CLAUDE.md` and `NOTES.md` are used here instead. Not
  installed.
- 2026-11-07: Built a `freellm` plugin (sends easy work to a FreeLLM API
  server, github.com/tashfeenahmed/freellmapi), then removed it at the
  user's request. Idea parked: a hook that sends simple questions to a free
  model automatically. Only revisit if the user asks.
