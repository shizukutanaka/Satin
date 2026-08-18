# Satin

Satin is a 3D avatar desktop companion. It responds to what you type or say
using offline, rule-based dialogue (no LLM or network required), speaks via
text-to-speech, and tracks a growing relationship (affinity, memories, special
days). It runs as a GUI avatar, a headless CLI chat, or a web dashboard.
Everything it knows about you stays on your machine.

See [`SPECIFICATION.md`](SPECIFICATION.md) for the full specification,
architecture, and a strengths / weaknesses / improvements analysis.
Contributors and AI agents should also read
[`AGENT_WORKORDERS.md`](AGENT_WORKORDERS.md) — a strengths/weaknesses inventory
and ready-to-execute work-order cards (with the repo's design boundaries and
contribution conventions).

## Features

Satin is a desktop 3D avatar companion. Everything below runs **locally and
offline** — the dialogue, emotion and memory are dictionary/rule/BM25 based, with
no LLM and no network calls.

- **Remembers you** — your name, birthday, interests, and answers you gave it,
  plus a searchable conversation history (BM25 relevance recall)
- **A relationship that changes** — affinity across five levels, daily mood,
  milestones, gifts, anniversaries
- **Notices how you are** — wellbeing check-ins and change-point detection over
  your own recent messages
- **Refuses to be manipulative** — no retention hooks at goodbye, a dependence
  guardrail, named crisis lines, and a standing "I am an AI" disclosure
- **Privacy you can verify** — everything on disk at 0600, one-command total
  erasure, and an optional retention window
- **3D avatar** — load your own `.glb`/`.gltf`/`.vrm`, rendered with per-face
  shading, with autonomous idle behaviour and optional TTS
- **Headless too** — full conversation from the CLI, plus a local web dashboard
- **Bilingual** — Japanese and English throughout, including the dashboard

### Avatar Persona / Dialogue

The autonomous 3D avatar's spoken lines (idle chatter, rest phrases and
time-aware greetings) are no longer hardcoded — they are loaded from
`config/persona.json` and can be customized without editing source code. The
system supports per-language dialogue with the same fallback chain as the UI
i18n (requested language → `default_lang` → `en`), picks lines without
repeating the previous one, and greets the user differently by time of day
(morning / afternoon / evening / night).

```jsonc
// config/persona.json
{
  "name": "Satin",
  "default_lang": "ja",
  "dialogue": {
    "ja": {
      "talk":  ["こんにちは！", "走るの大好き！"],
      "rest":  ["ふう…ちょっと休憩。"],
      "greeting": {
        "morning":   ["おはよう！"],
        "afternoon": ["こんにちは！"],
        "evening":   ["こんばんは。"],
        "night":     ["こんな時間まで…おつかれさま。"]
      }
    },
    "en": { "talk": ["Hello!"], "rest": ["Phew, a short break."] }
  }
}
```

```python
from main.persona import get_persona

persona = get_persona()          # loads config/persona.json once (cached)
print(persona.name)              # "Satin"
print(persona.greeting())        # time-aware: "おはよう！" in the morning
print(persona.talk())            # a random idle line (never repeats the last)
```

If `config/persona.json` is missing or malformed, the avatar falls back to
built-in default phrases, so the feature degrades gracefully.

#### Replies to what you say

When you type a comment to the avatar (the autonomous + TTS companion view), it
now **replies** instead of just reading your words back. Replies are driven by
configurable keyword rules in the `responses` section of `config/persona.json` —
no LLM or network is involved, so it works fully offline:

```jsonc
// config/persona.json  →  "responses"
"responses": {
  "ja": {
    "rules": [
      { "keywords": ["こんにちは", "やあ"], "replies": ["こんにちは！会えてうれしいな。"] },
      { "keywords": ["ありがとう"],         "replies": ["どういたしまして！"] }
    ],
    "fallback": ["なるほど、そうなんだ。", "うんうん、聞いてるよ。"]
  }
}
```

```python
from main.persona import get_persona

persona = get_persona()
persona.respond("こんにちは")        # -> a greeting reply from the matching rule
persona.respond("今日はどうかな")     # -> a generic acknowledgment from "fallback"
```

Rules are matched in order (first keyword hit wins, case-insensitive substring),
replies never repeat the previous line, and if no rule matches the avatar gives a
friendly fallback acknowledgment. If the persona is unavailable or returns nothing
the avatar falls back to echoing your text, preserving the original behavior.

The avatar isn't purely reactive: every few exchanges it adds a **follow-up
question** from the `follow_up` list (e.g. *「ところで、今日はどんな一日だった？」*) to
keep the conversation going, instead of only acknowledging. Closer relationships
unlock more personal questions via an optional `follow_up_by_affinity` block.

#### Conversation history

Every exchange (your comment + the avatar's reply) is recorded to the avatar
event log (`avatar_event_log.jsonl`), so conversations show up in the existing
event tooling — the timeline viewer, the Flask dashboard's `/logs` page, and the
event report. You can also read the history programmatically:

```python
from main.conversation_log import get_conversation_log

log = get_conversation_log()
log.recent(10)        # last 10 conversation events (dicts, oldest first)
log.recent_texts(10)  # ["You: こんにちは", "Avatar: こんにちは！会えてうれしいな。", ...]
```

Logging failures (e.g. disk full) never interrupt the avatar's speech or UI.

#### Headless chat (CLI)

You can talk to the avatar from a terminal — no GUI, GPU or display required —
which is handy on a server, over SSH, or in CI. The chat uses the same persona,
rule-based responses and conversation logging as the 3D avatar:

```bash
python satin_launcher.py --chat          # uses the configured default language
python main/persona_cli.py --lang en     # force a language, skip dep checks
```

```text
Satin: Taro、こんにちは！調子はどう？
コマンド: /help 一覧 | /history 履歴 | /search <キーワード> 検索 | /callme <名前> 呼び名設定 | /birthday MM-DD 誕生日 | /like <好きなもの> 趣味記憶 | /forget <好きなもの> 忘れる | /gift <プレゼント> 贈る | /whoami 確認 | /forget-me 記憶を全消去 | /mood 好感度 | /reset-mood リセット | /recap 今日のまとめ | /stats 統計 | /name 名前 | /quit 終了
You: /callme Taro
Satin: わかった、これからはTaroって呼ぶね！
You: こんにちは
Satin: やっほー！元気だった？
You: /quit
Satin: またね！いつでも来てね。
```

Commands: `/help`, `/history` (recent conversation), `/search <keyword>` (search
history including rotated archives), `/callme <name>` (teach the avatar what to
call you), `/birthday MM-DD` (teach your birthday), `/like <thing>` /
`/forget <thing>` (remember/forget an interest), `/gift <item>` (give a gift —
`/gift list` shows the catalog), `/whoami` (show what the avatar remembers),
`/forget-me` (erase all stored personal data — name, birthday, interests, and
remembered facts; two-step confirm), `/mood` (current affinity),
`/reset-mood` (reset to neutral), `/recap` (today's summary), `/stats`
(conversation totals), `/name`, `/quit` (`/exit`, `/q`). EOF (Ctrl-D) or Ctrl-C
also ends the session cleanly. The loop accepts injectable input/output
functions, so it is fully unit-testable. The 3D GUI accepts the same slash
commands typed as comments (`/gift`, `/callme`, `/birthday`, `/like`,
`/forget`, `/whoami`, `/forget-me`, `/forget-all` (erase everything —
profile, conversation history, affinity, and avatar selection; two-step
confirm), `/mood`, `/reset-mood`, `/clear-log`, `/history`, `/search`,
`/recap`, `/feeling`, `/avatar`, `/stats`, `/help`).

#### The avatar remembers who you are

`/callme <name>` stores how you'd like to be addressed in
`config/user_profile.json` (a private, git-ignored file). Once set, the avatar
greets you by name and weaves it into its follow-up questions via a `{user}`
placeholder in the persona's `follow_up`/reply lines (falling back to a neutral
"you" / "きみ" when no name is known). You can erase everything the avatar
remembers about you at any time with the in-app `/forget-me` command (name,
birthday, interests, and remembered facts; the relationship affinity is kept —
use `/reset-mood` for that). The profile is also wiped by
`manage_satin data purge` along with the rest of your personal data.

#### Special days (dating-sim inspired)

Borrowing the most beloved mechanic of romance games (ときめきメモリアル / LovePlus
/ otome games), the avatar marks **special days** in real time:

- **Your birthday** — `/birthday MM-DD` teaches it, and on that day the avatar
  gives a heartfelt birthday greeting (using your name) and a one-time affinity
  boost. It celebrates only once per year and remembers across sessions.
- **Seasonal events** — New Year, Valentine's Day, White Day, Tanabata,
  Halloween, Christmas Eve/Day and New Year's Eve each get their own special
  greeting at session start, so the companion feels like it lives in real time.

These appear in the headless chat greeting and in the GUI autonomous greeting.

#### The avatar notices how *you* feel (wellbeing check-in)

Affinity tracks how the avatar feels about *you*; the **wellbeing** feature is
the mirror image — it notices how *you* have been feeling lately. It scans the
sentiment of your own recent messages (last few days, from the conversation log)
and gently reflects it back: a caring nudge when you've sounded down, shared joy
when you've been upbeat, and — importantly — **silence when there's no clear
signal** (it won't force a mood read from thin data). It reuses the same offline
sentiment keywords as the affinity system, so no LLM or network is involved.

```text
You: /feeling
Satin: 最近、少し元気がないみたいだね。無理しないで、いつでも話してね。
```

```python
from main.user_wellbeing import wellbeing_reflection

# Empathetic one-liner based on the last 3 days of your messages ("" if unclear)
print(wellbeing_reflection(days=3, lang="ja"))
```

In the CLI, `/feeling` (alias `/checkin`) shows the reflection. It reads only
*your* messages (avatar replies are ignored), needs at least 3 recent messages
to say anything, and only speaks up when one sentiment clearly dominates.

The avatar is also **proactive** about it: at the start of a chat session,
right after its greeting, it adds the wellbeing line on its own when there's a
clear recent trend (and says nothing otherwise, so it never nags).

#### Safety: when you say something serious

A companion is often the first place someone says the hardest thing out loud.
If a message expresses self-harm or suicidal ideation — or the hopelessness
that can precede it — Satin stops the ordinary conversation flow and answers
with three things, and only these three: a short acknowledgement, a plain
statement that it is an AI and not a professional, and **specific, named crisis
lines** (`crisis_support.py`). It offers no advice and attempts no therapy.

```text
You: 死にたい
Satin: …そこまでつらいんだね。話してくれて、ありがとう。
       わたしは AI で、専門家じゃないんだ。だから、ちゃんと力になれる人につながってほしい。
       ・よりそいホットライン 0120-279-338（24時間・通話無料）
       ・こころの健康相談統一ダイヤル 0570-064-556（お住まいの相談窓口へつながります）
       ・いますぐ危ないと感じるときは 119 番へ。
```

That message is deliberately **not scored**: it does not move the affinity
number, does not count as an interaction, is never stored as the answer to a
profile question, and gets no follow-up question tacked on. The relationship
game stops there. Detection is keyword-based and offline like everything else,
with common intensifier idioms (「死ぬほど眠い」, "dying to see it") excluded — and
it is a safety net, not a clinical risk assessment.

#### Venting doesn't cost you the relationship

Affinity measures how you treat the avatar; the wellbeing check-in measures how
*you* are doing. Both used to read the same polarity signal, so telling Satin
「今日は最悪な一日だった」 cost 9.6 affinity points — and since low affinity moves
replies toward the distant register (「…そう。」), the avatar got colder exactly
when you were having a hard time. `sentiment_target.py` fixes the target
attribution: a negative message only costs affinity if it is aimed at the
avatar. Self-criticism and venting are free.

```text
You: 自分が嫌い            → affinity unchanged   (about you)
You: 今日は最悪な一日だった  → affinity unchanged   (about your day)
You: あなたなんて嫌い       → affinity down        (about the avatar)
```

Only the *penalty* is cancelled, never a gain, and only when the target is
explicit — a bare 「つまらない」 behaves as before. The sentiment classifier
itself is untouched, so the wellbeing check-in still notices you're down.

#### Safety: you are always told this is an AI

The affinity system, the confession event and lines like 「大好きだよ」 simulate an
emotional relationship, so Satin says plainly what it is (`ai_disclosure.py`):
**at the start of every session, again after every three hours of continuing
interaction, and as a standing line in `/help`** — in the 3D GUI and the CLI
alike.

```text
Satin: （お知らせ）わたしは AI のコンピュータープログラムで、人間ではありません。
       人間のような感情を実際に持っているわけでもありません。
```

That cadence is the one New York's AI Companion Models Law and California
SB 243 require. Satin never asks for your age, so it cannot tell whether you
are a minor — the reminder applies to everyone and there is no switch to turn
it off. The timer lives in memory only: restarting the app starts a new session
and discloses again, so nothing extra is written to disk.

Satin also refuses to use **manipulative farewells** (`farewell_integrity.py`):
the six dark patterns companion apps deploy when a user says goodbye —
premature-exit guilt, FOMO hooks, feigned abandonment, pressure to answer one
more question, ignoring the goodbye, and coercive restraint. Every farewell line
Satin ships is audited for these in the test suite, and `Persona.respond()`
filters them out at runtime even from a hand-edited `config/persona.json`.

### Affinity / Mood (relationship that grows)

The avatar now remembers how your relationship develops. Positive words
(thanks, "I love you", "cute"…) raise its **affinity** while hostile words lower
it; the score (0–100) maps to five levels — distant / reserved / neutral /
friendly / close (よそよそしい〜親友). Affinity is persisted to `config/mood.json`,
so the relationship carries over between sessions. In the CLI, `/mood` shows the
current level, and each message you send nudges it.

```python
from main.mood import get_mood_tracker

mood = get_mood_tracker()
mood.register("ありがとう、大好き！")   # positive → affinity rises
print(mood.level, int(mood.affinity))  # e.g. "friendly 66"
```

Sentiment keywords and the per-hit deltas are customizable via an optional
`"mood"` block in `config/persona.json`. Each message can move affinity by at
most ±10 (so a single spammy line can't swing it), and the value is always
clamped to 0–100. Mood can be disabled with `--no-mood`.

The relationship is **visible**: the avatar's greeting changes with affinity. Add
a `greeting_by_affinity` block per language to give level-specific greetings
(e.g. a cold `distant` greeting and a warm `close` one); the rest fall through to
the normal time-of-day greeting.

```text
affinity 10 (distant):  Satin: あ、来たんだ。
affinity 50 (neutral):  Satin: お昼だね。ちゃんと休憩してる？
affinity 90 (close):    Satin: やっと来てくれた！今日は何して遊ぶ？
```

The relationship also has **memory of time**. Satin records when you first met
and, at greeting time, celebrates relationship anniversaries — 7, 30, 100 and 180
days, then yearly (*「今日で出会ってから30日だね。出会えて本当によかった！」*). Each
milestone is celebrated only once. If you've been away for over a day it also says
it missed you, and a `/reset-mood` (or the dashboard's reset) starts the
relationship over from scratch.

### Management CLI (`manage_satin`)

A headless admin tool for inspecting and maintaining Satin's state — useful on a
server, over SSH, or in scripts. No GUI required.

```bash
python main/manage_satin.py validate                 # syntax + semantic config check
python main/manage_satin.py mood show                # current affinity / level
python main/manage_satin.py mood reset               # reset affinity to neutral
python main/manage_satin.py mood export mood.json    # export / import affinity state
python main/manage_satin.py log show -n 50           # last 50 conversation lines
python main/manage_satin.py log search こんにちは      # keyword search (archives included)
python main/manage_satin.py log csv chat.csv         # export conversation to CSV
python main/manage_satin.py log clear                # wipe live log + rotated archives
python main/manage_satin.py backup list              # list sync backups
python main/manage_satin.py backup restore foo.zip   # restore a backup
python main/manage_satin.py persona show             # persona name / rule counts
python main/manage_satin.py persona respond "やあ"    # preview a reply (no log/mood side-effects)
python main/manage_satin.py summary                  # today's activity summary
python main/manage_satin.py data purge --dry-run     # preview every personal-data file
python main/manage_satin.py data purge               # erase ALL personal data (confirms first)
```

`validate` checks JSON syntax and also performs semantic checks: it loads
`persona.json` through the persona loader and verifies the `responses` rules, and
confirms `mood_config.json` positive/negative blocks are language→word-list maps.

#### Privacy: the right to be forgotten

Satin stores everything locally — conversation log (and rotated archives),
affinity state (`config/mood.json`) and the daily affinity history
(`config/mood_history.jsonl`). `data purge` erases **all** of it in one step so
you can hand off or wipe a machine cleanly. It lists exactly what will be deleted
and asks for confirmation first; use `--dry-run` to preview without deleting, or
`--yes` to skip the prompt in scripts. (Your customisations in
`config/mood_config.json` and `config/persona.json` are preferences, not memories,
so they are left untouched.)

#### Privacy: how long conversations are kept

Deleting everything is a blunt instrument — you may well want to keep the
relationship and drop the old raw text. The log is rotated at 5 MB × 5
generations, but that is a size cap for disk hygiene, not a retention policy: if
you chat occasionally, everything you have ever said stays forever. Set a window
in `config/config.json` and Satin prunes anything older on every launch:

```jsonc
{ "settings": { "conversation_retention_days": 90 } }   // 0 = keep forever (default)
```

```bash
python main/manage_satin.py log prune --days 90 --dry-run   # count first
python main/manage_satin.py log prune --days 90             # then prune
```

The default is **0 — keep forever, exactly as before**; upgrading never deletes
anything you didn't ask it to. Lines whose timestamp can't be read are never
treated as old, the live log is rewritten atomically and stays owner-only
(0600), and a rotated `.gz` archive is removed only when its rotation stamp is
older than the cutoff. This is the storage-limitation half of privacy (GDPR
Art. 5(1)(e)) that local-only storage alone doesn't give you.

### Web dashboard

The Flask dashboard (`python main/dashboard.py`, port 5003) surfaces the event
log, chat history (with search and text/CSV download), backups, cloud sync, mood
(with a daily affinity-history chart and milestone markers), stats and the daily
summary. A `GET /healthz` endpoint returns `{"status":"ok"}` for uptime probes.
All conversation/affinity pages are served `no-store` so private data is never
cached by the browser.

## Getting Started

### Prerequisites

- Python 3.8+
- Git

### Platform-Specific Requirements

#### Windows
- Windows 10 or later
- PowerShell 5.1 or later
- Visual C++ Redistributable

#### Mac
- macOS 10.14 (Mojave) or later
- Homebrew (for dependency management)
- Xcode Command Line Tools

### Installation

1. Clone the repository:
```bash
git clone https://github.com/shizukutanaka/Satin.git
cd Satin
```

2. Install dependencies (same file on every platform):
```bash
pip install -r setup/requirements.txt
```

3. (Optional) Run the platform setup script — checks Python, upgrades pip,
   and installs the dependencies above for you:
```bash
# Windows
setup\win\setup.bat

# Mac
setup/mac/setup.sh
```

### Configuration

The main configuration file is located at `config/config.json`. You can override settings using environment variables or by modifying the JSON file.

### Usage

```bash
# Windows — launch the GUI avatar
launch\win\run_satin.bat

# Mac — launch the GUI avatar
launch/mac/run_satin.sh

# Any platform — same entry point directly, with more modes:
python satin_launcher.py              # GUI avatar (default)
python satin_launcher.py --chat       # headless CLI chat (no GUI/TTS deps needed)
python satin_launcher.py --dashboard  # Flask web dashboard
python satin_launcher.py --validate   # validate config and exit
python satin_launcher.py --avatar-loader  # pick a .glb/.gltf/.vrm avatar; the main GUI renders it next launch
```

The selected model is drawn as a **shaded solid**: `gltf_utils` reads the mesh's
index buffer, computes flat face normals (as the glTF 2.0 spec requires when the
model carries no `NORMAL` attribute), and the GUI renders `GL_TRIANGLES` with a
per-face diffuse term. Models made only of points or line primitives fall back to
the earlier wireframe drawing, and with no model selected you get the sphere
placeholder — so an exotic or partly-broken file degrades instead of failing.

To back up your data, use `python main/manage_satin.py backup list` and the
dashboard's `/sync` page.

## Directory Structure

```
Satin/
├── satin_launcher.py  # Entry point: --chat / --dashboard / --manage / --validate
├── config/            # Runtime configuration + mood/profile state
├── main/              # Application code (dialogue, mood, TTS, GUI, dashboard)
│   └── i18n/          # Internationalization helpers + locales/ja.json, en.json
├── launch/            # Per-OS launch scripts (call satin_launcher.py)
│   ├── win/run_satin.bat
│   └── mac/run_satin.sh
├── setup/             # Install: requirements.txt + per-OS setup.bat / setup.sh
└── tests/             # unittest suite (one file per module, run with pytest)
```

## Development

### Running Tests

```bash
pip install -r setup/requirements.txt   # includes pytest / pytest-asyncio
python -m pytest tests/ -q
```

### Linting

```bash
pip install ruff
ruff check main/ tests/
```

Both are also what `setup/github-actions-ci.yml` runs (see [Contributing](#contributing)
for how to activate CI on this repository).

## Contributing

CI is defined in `setup/github-actions-ci.yml` (lint + multi-version test
matrix) but not yet activated in this repository — a repository maintainer
with push access needs to copy it to `.github/workflows/ci.yml` once (see
the comment at the top of that file for the exact steps).

### Platform-Specific Guidelines

#### Windows
- Use `.bat` files for scripts
- Use Windows line endings (CRLF)
- Use Windows-style paths (\)
- Test on Windows 10 or later

#### Mac
- Use `.sh` files for scripts
- Use Unix line endings (LF)
- Use Unix-style paths (/)
- Test on macOS 10.14 or later

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License

## Support

For support, please open an issue in the GitHub repository.
