# CLAUDE.md

Read automatically at the start of every session on this repo.

## Start of every session

1. Read `NOTES.md`. It says what was done last, what is half finished and
   what is next. Pick up from there if the user asks to continue.
2. Then do what the user asks.

## End of every task

After each task that changes something (or settles a decision), update
`NOTES.md`, then commit and push it with the rest of the work, so the next
session knows where things stand. Keep `NOTES.md` short: replace stale
entries instead of piling them up, and keep "Log" to the last 15 or so items.

## About the user

- Not a programmer. Explain in plain words, skip jargon, and say what each
  step does and why. Give exact commands to copy when they need to run
  something on their own computer.
- Interested in day trading with the skills in this repo, in saving Claude
  usage, and in tools that give Claude memory between sessions.
- Ask before adding new tools or plugins to the repo; say what they cost and
  what they cannot do (for example, cloud sessions cannot reach `localhost`
  on the user's computer).

## About this repo

A fork of Jake Schincariol's Day Trader skill pack: 11 Claude skills for day
trading, each a folder at the root (`trader-scanner`, `trader-news`,
`trader-entry`, `trader-exit`, `trader-timemachine`, `trader-risk`,
`trader-budget`, `trader-broker`, `trader-alerts`, `trader-analyst`,
`trader-pelosi`) with a `SKILL.md` and a plain Python tool. It is also a
Claude Code plugin and marketplace (`.claude-plugin/`). Skills write their
output to a `trader/` folder in the user's project. The README has the full
tour.

Rules the tests enforce (`cd tests && python3 -B -m unittest -q`, run before
every commit):

- The root holds only the 11 skill folders, `.claude-plugin`, `tests`,
  `LICENSE`, `README.md`, `CLAUDE.md`, `NOTES.md` and `.gitignore`. A new
  root item means updating `tests/test_repo.py`.
- Python tools use the standard library only and run on Python 3.8.
- No em dash characters in any file outside `tests/fixtures`.
- Skills on the way to an order say "not financial advice" and never act
  without the user's yes. Paper trading is the default. Never weaken this.
- Never commit `__pycache__` (it is in `.gitignore`).
