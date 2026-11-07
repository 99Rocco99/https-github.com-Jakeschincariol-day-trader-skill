# NOTES.md

Where things stand, kept current by Claude at the end of each task. Newest
first.

## In progress

Nothing.

## Next

Nothing planned. Ask the user.

## Log

- 2026-11-07: Checked the branch (only CLAUDE.md, NOTES.md, .gitignore and
  one test line changed; no trading code touched), then opened a pull
  request and merged it into `main`.
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
