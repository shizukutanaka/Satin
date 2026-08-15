import html as _html
import os
import json
from datetime import datetime
from functools import wraps

try:
    from mood import (
        get_mood_tracker as _get_mood_tracker,
        affinity_label,
        level_label as _level_label,
        load_mood_history as _load_mood_history,
        _default_mood_history_path as _mood_history_path,
        _default_mood_path as _mood_path,
        mood_history_to_csv as _mood_history_to_csv,
    )
except Exception:
    _get_mood_tracker = None
    affinity_label = None
    _level_label = None
    _load_mood_history = None
    _mood_history_path = None
    _mood_path = None
    _mood_history_to_csv = None

try:
    from daily_summary import daily_summary as _daily_summary, summary_greeting as _summary_greeting
except Exception:
    _daily_summary = None
    _summary_greeting = None

# 会話イベント分類・既定ログパスは conversation_log を唯一の真実の源とする
# （集計の食い違い・cwd 依存でのファイル分裂を防ぐ）。
try:
    from conversation_log import (
        USER_EVENT_TYPES as _USER_TYPES,
        AVATAR_EVENT_TYPES as _AVATAR_TYPES,
        DEFAULT_LOGFILE as _DEFAULT_EVENT_LOG,
    )
except Exception:
    _USER_TYPES = {"user_comment", "user"}
    _AVATAR_TYPES = {"avatar_reply", "avatar"}
    _DEFAULT_EVENT_LOG = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "avatar_event_log.jsonl",
    )


def _get_persona_name(fallback: str = "Avatar") -> str:
    """ペルソナ名を返す。取得できない場合は fallback。リクエストごとに呼んでよい（軽量）。"""
    try:
        from persona import get_persona
        p = get_persona()
        if p and p.name:
            return p.name
    except Exception:
        pass
    return fallback

try:
    from flask import Flask, render_template_string, request, redirect, url_for, send_file, session, abort
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False
    Flask = render_template_string = request = redirect = url_for = send_file = session = abort = None  # type: ignore

try:
    from i18n import I18N
except ImportError:
    from importlib.util import spec_from_file_location as _spec, module_from_spec as _mfs
    import os as _os
    _spec_obj = _spec("satin_i18n", _os.path.join(_os.path.dirname(__file__), "i18n.py"))
    _i18n_mod = _mfs(_spec_obj)
    _spec_obj.loader.exec_module(_i18n_mod)
    I18N = _i18n_mod.I18N

def _no_cache(response):
    """会話・感情データは個人情報。ブラウザキャッシュへの保存を禁止する。

    全ルートに after_request で適用する。Flask 未使用時でも参照可能にするため
    Flask 依存ブロックの外に定義する。
    """
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response


if _FLASK_AVAILABLE:
    app = Flask(__name__)
    # ハードコードされた秘密鍵はセッション/CSRF 偽造を許す。環境変数を優先し、
    # 未設定ならプロセス毎のランダム値にフォールバックする。
    app.secret_key = os.environ.get('SATIN_DASHBOARD_SECRET') or os.urandom(24).hex()
    # セッション Cookie の安全側既定。Flask の素のデフォルトは SAMESITE/SECURE
    # 未設定でクロスサイト POST に弱いため、明示的に強化する:
    #   HTTPONLY=True   — JS から document.cookie で読めない（XSS 被害を限定）
    #   SAMESITE='Lax'  — 外部サイトからの POST/iframe に Cookie を載せない（CSRF 軽減）
    #   SECURE=opt-in   — HTTPS 配信時は SATIN_DASHBOARD_HTTPS=1 で Cookie を HTTPS 限定に
    #   LIFETIME=12h    — 漏洩 Cookie のリプレイ可能期間を短く
    import datetime as _dt
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=(os.environ.get('SATIN_DASHBOARD_HTTPS') == '1'),
        PERMANENT_SESSION_LIFETIME=_dt.timedelta(hours=12),
    )
    app.after_request(_no_cache)
else:
    class _NoopApp:
        def route(self, *a, **kw): return lambda f: f
        def after_request(self, f): return f
        secret_key = ""
    app = _NoopApp()  # type: ignore

event_log_path = _DEFAULT_EVENT_LOG
# 相対パスだと cwd 次第でバックアップ zip の置き場所が変わる（実際に起きた:
# ダッシュボードのバックアップ操作でリポジトリ直下に event_report/ が生成された）。
# _ROOT からの絶対パスに固定する。
backup_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "event_report",
)

# ダッシュボードの既定ポート。satin_launcher.py と dashboard.py の __main__ が
# 同じ値を参照することで、起動経路によるポート不整合（5000 vs 5003）を防ぐ。
# 環境変数 SATIN_DASHBOARD_PORT で上書き可能。
DEFAULT_DASHBOARD_PORT = 5003


def _resolve_port(default: int = DEFAULT_DASHBOARD_PORT) -> int:
    """SATIN_DASHBOARD_PORT を優先してポート番号を解決する。

    値が未設定／非数値／範囲外（1-65535）なら default にフォールバックする
    （不正値で起動失敗しない）。
    """
    raw = os.environ.get('SATIN_DASHBOARD_PORT')
    if raw:
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
        except (TypeError, ValueError):
            pass
    return default


def _build_sync_backup(zip_path, config_dir, log_path):
    """設定一式（config/ 配下を再帰的に）と会話ログ（アーカイブ含む）を zip にまとめる。

    旧実装は config/ 直下のファイルのみを対象にしており、config/plugins/*.json
    （i18n / logging / cache / performance / break_reminder の設定）が丸ごと
    バックアップから漏れていた。os.walk で再帰し全サブディレクトリを含める。

    ローテートされた <logfile>.<timestamp>.gz アーカイブも同梱する。これにより
    機種変更・再インストール時にも過去の全会話履歴を復元できる（ログローテーション
    後に /sync を取ると旧履歴が失われていた問題の修正）。

    Flask 非依存の純ロジックとして切り出し、テスト可能にする。
    Returns: zip に書き込んだ arcname のリスト。
    """
    import zipfile
    written = []
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        if config_dir and os.path.isdir(config_dir):
            for root, _dirs, files in os.walk(config_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arc = os.path.join('config', os.path.relpath(fpath, config_dir))
                    zf.write(fpath, arc)
                    written.append(arc)
        if log_path:
            if os.path.exists(log_path):
                arc = os.path.basename(log_path)
                zf.write(log_path, arc)
                written.append(arc)
            # ローテートされた gzip アーカイブも同梱（会話履歴の完全バックアップ）
            try:
                from conversation_log import _find_archives
                for gz_path in _find_archives(log_path):
                    arc = os.path.basename(gz_path)
                    zf.write(gz_path, arc)
                    written.append(arc)
            except Exception:
                pass
    # sync バックアップ zip は config/mood.json / user_profile.json / 会話ログ
    # (avatar_event_log.jsonl + 圧縮アーカイブ) を含む — 全て個人データ。
    # umask 既定だと他ユーザーが読めてしまうため所有者のみ読み書き可へ制限する。
    try:
        from fsutil import restrict_to_owner
        restrict_to_owner(zip_path)
    except Exception:
        pass  # 権限制限は best-effort。失敗時もバックアップ生成自体は成功。
    return written


def _safe_backup_path(fname):
    """backup_dir 内に収まる実パスのみを返す。ディレクトリトラバーサル
    (例: ../../etc/passwd) を防ぐため、解決後のパスが backup_dir 配下に
    あることを検証する。範囲外なら None。
    """
    base = os.path.abspath(backup_dir)
    target = os.path.abspath(os.path.join(base, fname))
    if target != base and not target.startswith(base + os.sep):
        return None
    return target

# LANG_SWITCHER_HTML (below) only ever offers these two as selectable
# options — nothing downstream should accept anything else.
_SUPPORTED_DASHBOARD_LANGS = {'en', 'ja'}

def get_lang():
    """クエリ/セッションから表示言語を取得する。

    以前は request.args.get('lang') の値を検証せず session に格納し、
    その後 f'...?lang={lang}' のように content 変数へ生の文字列として
    埋め込んでいた（/backups, /sync ルート）。content は
    render_template_string 側で {{ content|safe }} と Jinja2 の
    自動エスケープを明示的に無効化して描画されるため、
    ?lang="><script>...</script> のような値がそのまま反射型 XSS として
    実行されてしまう。加えて未検証の値は i18n.py の
    プロセス全体で共有される _translation_cache のキーにもなり、
    無制限にエントリを増やせるメモリ枯渇 DoS にもなっていた。
    ここで既知の言語のみに制限することで両方を根本から塞ぐ。
    """
    lang = request.args.get('lang') or session.get('lang')
    if lang in _SUPPORTED_DASHBOARD_LANGS:
        session['lang'] = lang
        return lang
    # 明示設定（SATIN_LANG）はブラウザの申告より優先する。運用者が言語を
    # 固定したいときの唯一の手段であり、アプリ本体（persona）とも共有される。
    explicit = os.environ.get('SATIN_LANG')
    if explicit:
        explicit = explicit.lower().split('_')[0].split('-')[0]
        if explicit in _SUPPORTED_DASHBOARD_LANGS:
            return explicit
    # 明示設定が無ければブラウザの Accept-Language を尊重する（RFC 9110 の
    # プロアクティブ内容折衝）。ダッシュボードはサーバー上で動き、ブラウザは
    # 別マシンということもあるので、サーバーの OS ロケールより利用者本人の
    # ブラウザ設定のほうが良い推定になる。best_match は q 値順に評価し、
    # 一致が無ければ None を返す。werkzeug 同梱なので新規依存は無い。
    try:
        negotiated = request.accept_languages.best_match(
            sorted(_SUPPORTED_DASHBOARD_LANGS))
    except Exception:  # pragma: no cover - defensive: 壊れたヘッダで 500 にしない
        negotiated = None
    if negotiated in _SUPPORTED_DASHBOARD_LANGS:
        return negotiated
    # detect_language() reads SATIN_LANG/the OS locale, not the HTTP request,
    # so it isn't attacker-controlled per-request — but it also isn't
    # guaranteed to be 'en'/'ja' (e.g. a French system locale), and this
    # value flows into the same unescaped f'...?lang={lang}' HTML embedding
    # as the query-param path above. Clamp it too for the same reason.
    detected = I18N().detect_language()
    return detected if detected in _SUPPORTED_DASHBOARD_LANGS else 'en'

def with_lang(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        lang = get_lang()
        i18n = I18N(lang)
        return f(i18n, *args, **kwargs)
    return wrapper

def _get_csrf_token() -> str:
    """セッションに紐づく CSRF トークンを取得（無ければ新規発行）する。

    /mood/reset・/sync は状態変更を伴う POST だが、これまでトークンも
    Origin/Referer 検証も一切無かった。SESSION_COOKIE_SAMESITE='Lax' が
    コメントで CSRF 対策として言及されていたが、これらのルート自体が
    session の中身を一切見ずに無条件でアクションを実行していたため、
    Cookie がクロスオリジン POST に付かないこと自体は防御として機能して
    いなかった（見られていないので意味がない）。悪意あるページが別タブで
    開かれているだけで、隠しフォームの自動送信により無確認で好感度が
    リセットされたり、バックアップ zip が量産されうる（ディスク圧迫 DoS）。
    セッションに紐づくランダムトークンをフォームに埋め込み、サーバー側で
    検証することで、同一オリジンでページを読み込んでいない限り
    トークンを知り得ない状態にする。
    """
    token = session.get('csrf_token')
    if not token:
        import secrets
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token

def _csrf_field() -> str:
    return f'<input type="hidden" name="csrf_token" value="{_html.escape(_get_csrf_token())}">'

def _verify_csrf() -> bool:
    import hmac
    submitted = request.form.get('csrf_token', '')
    expected = session.get('csrf_token', '')
    return bool(expected) and hmac.compare_digest(submitted, expected)

def require_csrf(f):
    """POST ルートに CSRF トークン検証を強制するデコレータ。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == 'POST' and not _verify_csrf():
            abort(403)
        return f(*args, **kwargs)
    return wrapper

LANG_SWITCHER_HTML = '''<form method="get" style="display:inline">
<select name="lang" onchange="this.form.submit()">
  <option value="en" {en}>English</option>
  <option value="ja" {ja}>日本語</option>
</select></form>'''

TEMPLATE = '''
<html><head><title>{{i18n.t('title')}}</title></head>
<body style="font-family:sans-serif;">
<h2>{{i18n.t('title')}}</h2>
<div style="float:right">''' + LANG_SWITCHER_HTML + '''</div>
<ul>
  <li><a href="/logs?lang={{lang}}">{{i18n.t('event_log')}}</a></li>
  <li><a href="/conversation?lang={{lang}}">{{i18n.t('conversation', 'Chat')}}</a></li>
  <li><a href="/conversation/search?lang={{lang}}">{{i18n.t('search', 'Search')}}</a></li>
  <li><a href="/backups?lang={{lang}}">{{i18n.t('backups')}}</a></li>
  <li><a href="/sync?lang={{lang}}">{{i18n.t('cloud_sync')}}</a></li>
  <li><a href="/mood?lang={{lang}}">{{i18n.t('mood', 'Mood')}}</a></li>
  <li><a href="/stats?lang={{lang}}">{{i18n.t('stats', 'Stats')}}</a></li>
  <li><a href="/summary?lang={{lang}}">{{i18n.t('summary', 'Summary')}}</a></li>
</ul>
<hr>
{% block content %}{{ content|safe }}{% endblock %}
</body></html>
'''


def _render_page(content, i18n, lang, switcher):
    """Render a page with `content` passed as a CONTEXT VARIABLE, never
    concatenated into the template source.

    Security: the previous pattern did
        render_template_string(TEMPLATE + '{% block content %}' + content + ...)
    which fed user-controlled conversation text into the Jinja parser. _html.escape
    stops <>&"' but NOT {{ }} / {% %}, so a comment like {{7*7}} became Server-Side
    Template Injection (→ RCE). Passing content as a variable means Jinja renders it
    as a string and does not re-parse {{ }} inside it; user text is already
    _html.escape'd so |safe only re-emits the intended (escaped) HTML.
    """
    return render_template_string(
        TEMPLATE, content=content, i18n=i18n, lang=lang, switcher=switcher
    )

@app.route('/')
@with_lang
def index(i18n):
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(en='selected' if lang=='en' else '', ja='selected' if lang=='ja' else '')
    # Build summary stats block
    stats_lines = []
    # Conversation count (archives included so rotation doesn't reset the counter)
    try:
        from conversation_log import ConversationLog
        total = len([
            ev for ev in ConversationLog(event_log_path).search("", include_archives=True)
            if ev.get("event_type") in _USER_TYPES
        ])
        stats_lines.append(f'{_html.escape(i18n.t("total_messages", "Total messages"))}: <b>{total}</b>')
    except Exception:
        pass
    # Current affinity
    if _get_mood_tracker is not None:
        try:
            tracker = _get_mood_tracker()
            score = int(round(tracker.affinity))
            level = affinity_label(tracker.affinity, lang) if affinity_label else tracker.level
            stats_lines.append(f'{_html.escape(i18n.t("affinity_score", "Affinity"))}: <b>{score}/100</b> ({_html.escape(level)})')
        except Exception:
            pass
    stats_html = ''
    if stats_lines:
        stats_html = '<ul>' + ''.join(f'<li>{s}</li>' for s in stats_lines) + '</ul>'
    content = stats_html
    return _render_page(content, i18n, lang, switcher)

@app.route('/logs')
@with_lang
def logs(i18n):
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(en='selected' if lang=='en' else '', ja='selected' if lang=='ja' else '')
    events = []
    if os.path.exists(event_log_path):
        with open(event_log_path, encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    ev = json.loads(line)
                    ts = datetime.fromtimestamp(ev['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    events.append({'ts': ts, 'type': ev['event_type'], 'details': ev['details']})
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    continue  # 壊れた/不完全な行はスキップしてページ全体を落とさない
    content = f'<h3>{i18n.t("event_log")}</h3><table border=1 cellpadding=4><tr>' \
        f'<th>{i18n.t("time")}</th><th>{i18n.t("type")}</th><th>{i18n.t("details")}</th></tr>'
    for e in events[-100:]:
        content += (
            f"<tr><td>{_html.escape(e['ts'])}</td>"
            f"<td>{_html.escape(str(e['type']))}</td>"
            f"<td>{_html.escape(str(e['details']))}</td></tr>"
        )
    content += '</table>'
    return _render_page(content, i18n, lang, switcher)

@app.route('/backups')
@with_lang
def backups(i18n):
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(en='selected' if lang=='en' else '', ja='selected' if lang=='ja' else '')
    files = []
    if os.path.isdir(backup_dir):
        files = [f for f in os.listdir(backup_dir) if f.endswith('.png') or f.endswith('.gz') or f.endswith('.zip')]
    content = f'<h3>{i18n.t("backups")}</h3><ul>'
    for f in files:
        f_esc = _html.escape(f)
        content += f'<li><a href="/download/{f_esc}?lang={lang}">{f_esc}</a></li>'
    content += '</ul>'
    return _render_page(content, i18n, lang, switcher)

@app.route('/download/<fname>')
@with_lang
def download(i18n, fname):
    path = _safe_backup_path(fname)
    if path and os.path.isfile(path):
        return send_file(path, as_attachment=True)
    return i18n.t('no_file'), 404

@app.route('/sync', methods=['GET', 'POST'])
@require_csrf
@with_lang
def sync(i18n):
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(en='selected' if lang=='en' else '', ja='selected' if lang=='ja' else '')
    msg = ''
    msg_color = 'green'
    backup_path_display = ''
    if request.method == 'POST':
        try:
            import datetime as _dt
            # Create a zip of config/ (recursively, incl. plugins/) and the
            # conversation log in the event_report/ dir.
            os.makedirs(backup_dir, exist_ok=True)
            ts = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
            zip_name = f'backup_{ts}.zip'
            zip_path = os.path.join(backup_dir, zip_name)
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_dir = os.path.join(_root, 'config')
            _build_sync_backup(zip_path, config_dir, event_log_path)
            backup_path_display = zip_name
            msg = i18n.t('executed_cloud_sync')
        except Exception as exc:
            msg = _html.escape(str(exc))
            msg_color = 'red'

    # List existing backups
    existing = []
    if os.path.isdir(backup_dir):
        existing = sorted(
            f for f in os.listdir(backup_dir)
            if f.endswith('.gz') or f.endswith('.zip')
        )

    backup_info = ''
    if backup_path_display:
        backup_info = f'<p>{_html.escape(i18n.t("backup_saved_as", "Saved as"))}: <b>{_html.escape(backup_path_display)}</b></p>'
    existing_html = ''
    if existing:
        existing_html = f'<h4>{_html.escape(i18n.t("existing_backups", "Existing backups"))}</h4><ul>'
        for fn in existing[-10:]:
            fn_esc = _html.escape(fn)
            existing_html += f'<li><a href="/download/{fn_esc}?lang={lang}">{fn_esc}</a></li>'
        existing_html += '</ul>'

    content = f'''<h3>{_html.escape(i18n.t("cloud_sync"))}</h3>
<p>{_html.escape(i18n.t("sync_description", "Create a local backup of config files and conversation log."))}</p>
<form method="post">{_csrf_field()}<button type="submit">{_html.escape(i18n.t("manual_cloud_sync"))}</button></form>
{backup_info}
<p style="color:{msg_color}">{_html.escape(msg)}</p>
{existing_html}'''
    return _render_page(content, i18n, lang, switcher)

@app.route('/conversation')
@with_lang
def conversation(i18n):
    """会話履歴のみを表示する（user_comment / avatar_reply イベントをフィルタ）。"""
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(
        en='selected' if lang.startswith('en') else '',
        ja='selected' if not lang.startswith('en') else '',
    )
    from conversation_log import ConversationLog
    avatar_name = _get_persona_name(fallback=i18n.t('avatar', 'Avatar'))
    exchanges = []
    for ev in ConversationLog(event_log_path).search("", n=100, include_archives=True):
        try:
            et = ev.get('event_type', '')
            ts = datetime.fromtimestamp(ev['timestamp']).strftime('%H:%M:%S')
            speaker = (
                i18n.t('you', 'You') if et in _USER_TYPES
                else avatar_name
            )
            details = ev.get('details') or {}
            text = details.get('text', '') if isinstance(details, dict) else str(details)
            exchanges.append({'ts': ts, 'speaker': speaker, 'text': text})
        except (KeyError, ValueError, TypeError, OSError):
            continue
    title = i18n.t('conversation', 'Chat History')
    content = f'<h3>{_html.escape(title)}</h3>'
    if not exchanges:
        content += f'<p>{_html.escape(i18n.t("no_conversation", "No conversation history yet."))}</p>'
    else:
        content += '<table border=0 cellpadding=6 cellspacing=2 style="width:100%">'
        for ex in exchanges:
            is_user = ex['speaker'] == i18n.t('you', 'You')
            align = 'left' if is_user else 'right'
            bg = '#e8f4fd' if is_user else '#f0fde8'
            content += (
                f'<tr><td align="{align}" style="background:{bg};padding:6px 10px;'
                f'border-radius:8px;max-width:70%">'
                f'<small style="color:#888">{_html.escape(ex["ts"])}'
                f' <b>{_html.escape(ex["speaker"])}</b></small><br>'
                f'{_html.escape(str(ex["text"]))}</td></tr>'
            )
        content += '</table>'
    csv_label = i18n.t('csv_format', 'CSV')
    content += (
        f'<p>'
        f'<a href="/conversation/download?lang={_html.escape(lang)}">'
        f'{_html.escape(i18n.t("download_conversation", "Download as text"))}</a>'
        f' &nbsp;|&nbsp; '
        f'<a href="/conversation/download/csv?lang={_html.escape(lang)}">'
        f'{_html.escape(csv_label)}</a>'
        f'</p>'
    )
    return _render_page(content, i18n, lang, switcher)


@app.route('/conversation/download')
@with_lang
def conversation_download(i18n):
    """会話履歴をプレーンテキストとしてダウンロードする。アーカイブも含む完全版。"""
    import io
    from conversation_log import ConversationLog
    avatar_name = _get_persona_name(fallback=i18n.t('avatar', 'Avatar'))
    lines_out = []
    for ev in ConversationLog(event_log_path).search("", include_archives=True):
        try:
            et = ev.get('event_type', '')
            ts = datetime.fromtimestamp(ev['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            speaker = i18n.t('you', 'You') if et in _USER_TYPES else avatar_name
            details = ev.get('details') or {}
            text = details.get('text', '') if isinstance(details, dict) else str(details)
            lines_out.append(f'[{ts}] {speaker}: {text}')
        except (KeyError, ValueError, TypeError, OSError):
            continue
    text_content = '\n'.join(lines_out) + '\n'
    buf = io.BytesIO(text_content.encode('utf-8'))
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name='conversation.txt',
        mimetype='text/plain; charset=utf-8',
    )


@app.route('/conversation/download/csv')
@with_lang
def conversation_download_csv(i18n):
    """会話履歴を CSV としてダウンロードする（スプレッドシート用）。"""
    import io
    try:
        from conversation_log import ConversationLog
        log = ConversationLog(event_log_path)
        csv_content = log.to_csv(
            user_label=i18n.t('you', 'You'),
            avatar_label=_get_persona_name(fallback=i18n.t('avatar', 'Avatar')),
        )
    except Exception:
        csv_content = "timestamp,datetime,speaker,text\r\n"
    buf = io.BytesIO(csv_content.encode('utf-8-sig'))  # BOM for Excel compatibility
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name='conversation.csv',
        mimetype='text/csv; charset=utf-8',
    )


@app.route('/mood/history/csv')
@with_lang
def mood_history_csv(i18n):
    """好感度の日次履歴を CSV としてダウンロードする。"""
    import io
    csv_str = ""
    if _mood_history_to_csv is not None and _mood_history_path is not None:
        try:
            csv_str = _mood_history_to_csv(_mood_history_path(), n=365)
        except Exception:
            csv_str = ""
    if not csv_str and _load_mood_history is not None and _mood_history_path is not None:
        import csv
        rows = []
        try:
            rows = _load_mood_history(_mood_history_path(), n=365)
        except Exception:
            rows = []
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\r\n')
        writer.writerow(['date', 'datetime', 'affinity', 'level', 'interactions'])
        for e in rows:
            writer.writerow([
                e.get('date', ''), '',
                e.get('affinity', ''),
                e.get('level', ''),
                e.get('interactions', ''),
            ])
        csv_str = buf.getvalue()
    csv_bytes = io.BytesIO(csv_str.encode('utf-8-sig'))
    csv_bytes.seek(0)
    return send_file(
        csv_bytes,
        as_attachment=True,
        download_name='mood_history.csv',
        mimetype='text/csv; charset=utf-8',
    )


@app.route('/mood')
@with_lang
def mood(i18n):
    lang = get_lang()
    is_en = lang.startswith('en')
    switcher = LANG_SWITCHER_HTML.format(
        en='selected' if is_en else '', ja='selected' if not is_en else ''
    )
    if _get_mood_tracker is None:
        content = f'<h3>{i18n.t("mood", "Mood")}</h3><p>{i18n.t("mood_unavailable", "Mood system unavailable.")}</p>'
    else:
        try:
            tracker = _get_mood_tracker()
            score = int(round(tracker.affinity))
            level = tracker.level
            label = affinity_label(tracker.affinity, lang) if affinity_label else level
            interactions = tracker.interactions
            last_ts = tracker._last_interaction_time
            if last_ts > 0:
                last_dt = datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d %H:%M:%S')
            else:
                last_dt = i18n.t("mood_no_interactions_yet", "No interactions yet")
            # progress bar fill colour: red→yellow→green by score
            colour = f'hsl({int(score * 1.2)}, 70%, 45%)'
            reset_label = _html.escape(i18n.t("reset_mood", "Reset to neutral"))
            history_link = f'<a href="/mood/history?lang={_html.escape(lang)}">{_html.escape(i18n.t("mood_history", "Affinity History"))}</a>'
            content = f'''
<h3>{_html.escape(i18n.t("mood", "Mood"))}</h3>
<table border=0 cellpadding=6>
<tr><td><b>{_html.escape(i18n.t("affinity_score", "Affinity"))}</b></td>
    <td>{score}/100
      <div style="background:#ddd;width:200px;height:12px;display:inline-block;vertical-align:middle">
        <div style="background:{colour};width:{score * 2}px;height:12px"></div>
      </div>
    </td></tr>
<tr><td><b>{_html.escape(i18n.t("affinity_level", "Level"))}</b></td>
    <td>{_html.escape(label)}</td></tr>
<tr><td><b>{_html.escape(i18n.t("interactions", "Interactions"))}</b></td>
    <td>{interactions}</td></tr>
<tr><td><b>{_html.escape(i18n.t("last_interaction", "Last interaction"))}</b></td>
    <td>{_html.escape(last_dt)}</td></tr>
</table>
<p>{history_link}</p>
<br>
<form method="post" action="/mood/reset?lang={_html.escape(lang)}">
  {_csrf_field()}
  <button type="submit" onclick="return confirm('{reset_label}?')">
    {reset_label}
  </button>
</form>'''
        except Exception as exc:
            content = f'<h3>{i18n.t("mood", "Mood")}</h3><p>{_html.escape(str(exc))}</p>'
    return _render_page(content, i18n, lang, switcher)


@app.route('/mood/reset', methods=['POST'])
@require_csrf
@with_lang
def mood_reset(i18n):
    """好感度を neutral（50/100）にリセットして /mood にリダイレクトする。"""
    lang = get_lang()
    if _get_mood_tracker is not None:
        try:
            from mood import AFFINITY_START
            tracker = _get_mood_tracker()
            tracker.affinity = AFFINITY_START
            tracker.interactions = 0
            tracker._last_interaction_time = 0.0
            # リセットは「関係の仕切り直し」: 出会いの起点と記念日マーカーも消す
            tracker._first_interaction_time = 0.0
            tracker._last_anniversary_days = 0
            if _mood_path is not None:
                tracker.save(_mood_path())
        except Exception:
            pass
    if redirect is not None and url_for is not None:
        return redirect(url_for('mood', lang=lang))
    return i18n.t('mood', 'Mood'), 200


@app.route('/conversation/search')
@with_lang
def conversation_search(i18n):
    """会話履歴をキーワード検索し、一致した交換を表示する。"""
    lang = get_lang()
    is_en = lang.startswith('en')
    switcher = LANG_SWITCHER_HTML.format(
        en='selected' if is_en else '', ja='selected' if not is_en else ''
    )
    q = (request.args.get('q') or '').strip()
    q_esc = _html.escape(q)
    search_label = _html.escape(i18n.t('search', 'Search'))
    search_placeholder = _html.escape(i18n.t('search_placeholder', 'Enter keyword…'))
    content = f'''<h3>{search_label}</h3>
<form method="get">
  <input type="hidden" name="lang" value="{_html.escape(lang)}">
  <input type="text" name="q" value="{q_esc}" placeholder="{search_placeholder}" style="width:300px;padding:4px">
  <button type="submit">{search_label}</button>
</form>'''

    if q:
        # Reuse ConversationLog.search() for filtering (event-type + substring)
        # rather than reinventing the JSONL parse — keeps one search behavior.
        from conversation_log import ConversationLog
        avatar_name = _get_persona_name(fallback=i18n.t('avatar', 'Avatar'))
        matches = []
        for ev in ConversationLog(event_log_path).search(q):
            et = ev.get('event_type', '')
            details = ev.get('details') or {}
            text = details.get('text', '') if isinstance(details, dict) else str(details)
            try:
                ts = datetime.fromtimestamp(ev.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, OSError, OverflowError, TypeError):
                ts = ''
            speaker = i18n.t('you', 'You') if et in _USER_TYPES else avatar_name
            matches.append({'ts': ts, 'speaker': speaker, 'text': text})

        count_label = _html.escape(i18n.t('search_results', 'Results'))
        content += f'<p><b>{count_label}: {len(matches)}</b></p>'
        if matches:
            content += '<table border=0 cellpadding=6 cellspacing=2 style="width:100%">'
            for ex in matches[-200:]:
                is_user = ex['speaker'] == i18n.t('you', 'You')
                align = 'left' if is_user else 'right'
                bg = '#e8f4fd' if is_user else '#f0fde8'
                # Highlight the matched keyword
                highlighted = _html.escape(ex['text']).replace(
                    _html.escape(q), f'<mark>{_html.escape(q)}</mark>'
                )
                content += (
                    f'<tr><td align="{align}" style="background:{bg};padding:6px 10px;'
                    f'border-radius:8px;max-width:70%">'
                    f'<small style="color:#888">{_html.escape(ex["ts"])}'
                    f' <b>{_html.escape(ex["speaker"])}</b></small><br>'
                    f'{highlighted}</td></tr>'
                )
            content += '</table>'

    return _render_page(content, i18n, lang, switcher)


@app.route('/mood/history')
@with_lang
def mood_history(i18n):
    """好感度の日次履歴を棒グラフ形式で表示する。"""
    lang = get_lang()
    is_en = lang.startswith('en')
    switcher = LANG_SWITCHER_HTML.format(
        en='selected' if is_en else '', ja='selected' if not is_en else ''
    )
    title = _html.escape(i18n.t("mood_history", "Affinity History"))
    content = f'<h3>{title}</h3>'

    if _load_mood_history is None:
        content += f'<p>{_html.escape(i18n.t("mood_unavailable", "Mood system unavailable."))}</p>'
    else:
        history_path = _mood_history_path() if _mood_history_path else None
        entries = _load_mood_history(history_path, n=30) if history_path else []
        if not entries:
            content += f'<p>{_html.escape(i18n.t("mood_no_history", "No history recorded yet."))}</p>'
        else:
            content += '<table border=0 cellpadding=4 cellspacing=2>'
            content += f'<tr><th>{_html.escape(i18n.t("date", "Date"))}</th>'
            content += f'<th>{_html.escape(i18n.t("affinity_score", "Affinity"))}</th>'
            content += '<th></th>'
            content += f'<th>{_html.escape(i18n.t("affinity_level", "Level"))}</th>'
            content += f'<th>{_html.escape(i18n.t("milestone", "Milestone"))}</th></tr>'
            for e in entries:
                # affinity が null / 非数値でも 500 にせず 0 として描画する
                # （手編集・バックアップ復元で壊れた履歴行への防御）。
                affinity_val = _coerce_affinity(e.get("affinity"))
                score = int(round(affinity_val))
                # 内部キーではなく表示ラベルで描画する（日本語 UI に "friendly"
                # のような英語識別子が混ざるのを防ぐ）。矢印の向き判定には
                # 下の _level_rank が生キーを使い続ける。
                level = _html.escape(_localized_level(str(e.get("level", "")), lang))
                date = _html.escape(str(e.get("date", "")))
                colour = f'hsl({int(score * 1.2)}, 70%, 45%)'
                bar_width = max(1, score * 2)
                # マイルストーン列: レベル変化があった行に矢印と前後レベルを表示
                milestone_html = ""
                if e.get("level_changed"):
                    prev = _html.escape(
                        _localized_level(str(e.get("prev_level", "?")), lang))
                    # Compare level ranks, not raw affinity, to get the correct
                    # direction. Old bug: affinity_val >= 50 showed UP even when
                    # transitioning close→friendly (a decrease in level).
                    arrow = ("&#8593;"
                             if _level_rank(str(e.get("level", ""))) > _level_rank(str(e.get("prev_level", "")))
                             else "&#8595;")
                    milestone_html = (
                        f'<span style="color:#e07000;font-weight:bold">'
                        f'{arrow} {prev} &rarr; {level}'
                        f'</span>'
                    )
                content += (
                    f'<tr>'
                    f'<td>{date}</td>'
                    f'<td style="text-align:right">{score}</td>'
                    f'<td><div style="background:#ddd;width:200px;height:10px;display:inline-block;vertical-align:middle">'
                    f'<div style="background:{colour};width:{bar_width}px;height:10px"></div>'
                    f'</div></td>'
                    f'<td>{level}</td>'
                    f'<td>{milestone_html}</td>'
                    f'</tr>'
                )
            content += '</table>'
        csv_lbl = i18n.t('download_csv', 'Download CSV')
        content += (
            f'<p>'
            f'<a href="/mood?lang={_html.escape(lang)}">&larr; {_html.escape(i18n.t("back_to_mood", "Back to Mood"))}</a>'
            f' &nbsp;|&nbsp; '
            f'<a href="/mood/history/csv?lang={_html.escape(lang)}">{_html.escape(csv_lbl)}</a>'
            f'</p>'
        )

    return _render_page(content, i18n, lang, switcher)


# Ordered lowest→highest, mirroring mood._LEVELS.
_LEVEL_ORDER = ["distant", "reserved", "neutral", "friendly", "close"]


def _localized_level(level_key: str, lang: str) -> str:
    """保存済みレベルキーを表示ラベルへ変換する（mood 未導入時はキーのまま）。

    `config/mood_history.jsonl` の level / prev_level は内部キー（"friendly"
    等の英語識別子）で保存されるため、そのまま描画すると日本語 UI に英語が
    混ざる。ラベルの定義は mood._LEVELS を単一の真実の源とする。
    """
    if _level_label is None:
        return str(level_key or "")
    return _level_label(level_key, lang)


def _level_rank(name: str) -> int:
    """Return ordinal rank of a level name; -1 for unknown."""
    try:
        return _LEVEL_ORDER.index(name)
    except ValueError:
        return -1


def _coerce_affinity(value, default: float = 0.0) -> float:
    """好感度値を安全に float へ変換する（Flask 非依存・テスト可能）。

    JSON の ``"affinity": null`` は dict.get の既定値を経由せず None を返すため、
    float(None) が TypeError を送出して /mood/history が 500 になる。手編集や
    バックアップ復元で壊れた履歴行に対し、None / 非数値なら default を返す。
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _conversation_stats(log_path: str) -> dict:
    """JSONL ログから会話統計を集計して辞書で返す（Flask 非依存）。

    ローテートされた .gz アーカイブも含む全期間の統計を返す。
    アーカイブを無視すると、ローテーション後に統計グラフが空になる問題を防ぐ。

    Returns:
        {
          "total_user": int,
          "total_avatar": int,
          "per_day": {date_str: int},   # user messages per day
          "peak_hour": int | None,       # 0-23, most active hour by user messages
          "per_hour": {0..23: int},
        }
    """
    from collections import defaultdict
    from conversation_log import ConversationLog
    total_user = 0
    total_avatar = 0
    per_day: dict = defaultdict(int)
    per_hour: dict = defaultdict(int)
    try:
        for ev in ConversationLog(log_path).search("", include_archives=True):
            et = ev.get('event_type', '')
            ts = ev.get('timestamp', 0)
            try:
                if et in _USER_TYPES:
                    total_user += 1
                    dt = datetime.fromtimestamp(ts)
                    per_day[dt.strftime('%Y-%m-%d')] += 1
                    per_hour[dt.hour] += 1
                elif et in _AVATAR_TYPES:
                    total_avatar += 1
            except (ValueError, OSError, OverflowError, TypeError):
                # TypeError: fromtimestamp(None) or fromtimestamp("str") when
                # the event has "timestamp": null or a non-numeric value.
                # The count was already incremented above; skip time-based stats.
                continue
    except Exception:
        pass
    peak_hour = max(per_hour, key=per_hour.get) if per_hour else None
    return {
        "total_user": total_user,
        "total_avatar": total_avatar,
        "per_day": dict(sorted(per_day.items())),
        "peak_hour": peak_hour,
        "per_hour": {h: per_hour[h] for h in range(24)},
    }


@app.route('/stats')
@with_lang
def stats(i18n):
    """会話統計ページ: メッセージ数の推移・ピーク時間帯を可視化する。"""
    lang = get_lang()
    is_en = lang.startswith('en')
    switcher = LANG_SWITCHER_HTML.format(
        en='selected' if is_en else '', ja='selected' if not is_en else ''
    )
    title = _html.escape(i18n.t('stats', 'Stats'))
    content = f'<h3>{title}</h3>'

    s = _conversation_stats(event_log_path)
    total_user = s["total_user"]
    total_avatar = s["total_avatar"]
    per_day = s["per_day"]
    per_hour = s["per_hour"]
    peak_hour = s["peak_hour"]

    user_lbl = _html.escape(i18n.t('user_messages', 'User messages'))
    avatar_lbl = _html.escape(i18n.t('avatar_replies', 'Avatar replies'))
    content += (f'<p>{user_lbl}: <b>{total_user}</b> &nbsp; '
                f'{avatar_lbl}: <b>{total_avatar}</b></p>')

    if per_day:
        ph_label = i18n.t('messages_per_day', 'Messages per day')
        content += f'<h4>{_html.escape(ph_label)}</h4>'
        content += '<table border=0 cellpadding=3 cellspacing=2>'
        max_day = max(per_day.values()) if per_day else 1
        for day, cnt in list(per_day.items())[-30:]:
            bar = max(1, int(cnt / max_day * 200))
            content += (
                f'<tr><td style="text-align:right;padding-right:8px;white-space:nowrap">'
                f'{_html.escape(day)}</td>'
                f'<td style="text-align:right;padding-right:6px">{cnt}</td>'
                f'<td><div style="background:#5b9bd5;width:{bar}px;height:10px;display:inline-block"></div></td></tr>'
            )
        content += '</table>'

    if peak_hour is not None:
        peak_lbl = _html.escape(i18n.t('peak_activity', 'Peak activity'))
        content += (f'<p>{peak_lbl}: '
                    f'<b>{peak_hour:02d}:00–{peak_hour:02d}:59</b></p>')
        hr_label = i18n.t('messages_per_hour', 'Messages per hour')
        content += f'<h4>{_html.escape(hr_label)}</h4>'
        content += '<table border=0 cellpadding=2 cellspacing=2>'
        max_hr = max(per_hour.values()) if any(per_hour.values()) else 1
        # 時刻軸の単位は英語固定の "h" だった（日本語 UI でも "00h"）。
        hour_suffix = _html.escape(i18n.t('hour_suffix', 'h'))
        for h in range(24):
            cnt = per_hour.get(h, 0)
            bar = max(0, int(cnt / max_hr * 120)) if max_hr else 0
            content += (
                f'<tr><td style="text-align:right;padding-right:4px">'
                f'{h:02d}{hour_suffix}</td>'
                f'<td style="text-align:right;padding-right:4px">{cnt}</td>'
                f'<td><div style="background:#5b9bd5;width:{bar}px;height:8px;display:inline-block"></div></td></tr>'
            )
        content += '</table>'

    if not per_day:
        no_data = i18n.t('no_conversation_data', 'No conversation data yet.')
        content += f'<p>{_html.escape(no_data)}</p>'

    return _render_page(content, i18n, lang, switcher)


@app.route('/summary')
@with_lang
def summary(i18n):
    """今日のアクティビティサマリーとアバターの一言を表示する。"""
    lang = get_lang()
    is_en = lang.startswith('en')
    switcher = LANG_SWITCHER_HTML.format(
        en='selected' if is_en else '', ja='selected' if not is_en else ''
    )
    title = _html.escape(i18n.t('summary', 'Summary'))
    content = f'<h3>{title}</h3>'

    if _daily_summary is None:
        msg = i18n.t('summary_unavailable', 'Summary module unavailable.')
        content += f'<p>{_html.escape(msg)}</p>'
    else:
        s = _daily_summary(
            lang=lang,
            event_log_path=event_log_path,
            mood_history_path=_mood_history_path() if _mood_history_path else None,
        )
        # アバターの一言
        greeting = ''
        if _summary_greeting is not None:
            greeting = _summary_greeting(
                lang=lang,
                event_log_path=event_log_path,
                mood_history_path=_mood_history_path() if _mood_history_path else None,
            )
        if greeting:
            content += (
                f'<blockquote style="background:#f0f6ff;border-left:4px solid #5b9bd5;'
                f'padding:8px 12px;margin:8px 0;font-style:italic">'
                f'{_html.escape(greeting)}</blockquote>'
            )

        date_lbl = i18n.t('date', 'Date')
        user_lbl = i18n.t('your_messages', 'Your messages')
        _aname = _get_persona_name()
        # 語順が言語で入れ替わる（"Mimi replies" / "Mimiの返答"）ので、位置を
        # 翻訳側の {name} プレースホルダに委ねる。翻訳値に波括弧が混ざっても
        # 例外にならないよう .format ではなく replace を使う。
        avatar_lbl = i18n.t('avatar_replies_of', '{name} replies').replace(
            '{name}', _aname)
        total_lbl = i18n.t('total_interactions', 'Total interactions')
        peak_lbl = i18n.t('peak_hour', 'Peak hour')
        affinity_lbl = i18n.t('affinity', 'Affinity')

        peak = s['peak_hour']
        peak_str = f'{peak:02d}:00–{peak:02d}:59' if peak is not None else '—'
        # daily_summary の affinity_level は mood_history の生キー
        # （"friendly" 等）なので、表示前にラベル化する。
        affinity_str = (
            f'{s["affinity"]:.1f} '
            f'({_html.escape(_localized_level(str(s["affinity_level"]), lang))})'
            if s['affinity'] is not None else '—'
        )
        rows = [
            (date_lbl, _html.escape(s['date'])),
            (user_lbl, str(s['user_messages'])),
            (avatar_lbl, str(s['avatar_replies'])),
            (total_lbl, str(s['total_interactions'])),
            (peak_lbl, peak_str),
            (affinity_lbl, affinity_str),
        ]
        content += '<table border=0 cellpadding=5 cellspacing=2>'
        for label, value in rows:
            content += (
                f'<tr><td style="text-align:right;color:#666">{_html.escape(label)}:</td>'
                f'<td><b>{value}</b></td></tr>'
            )
        content += '</table>'

    return _render_page(content, i18n, lang, switcher)


@app.route('/healthz')
def healthz():
    """ヘルスチェックエンドポイント。監視ツールやプロキシが生死確認に使う。"""
    from flask import jsonify
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    # debug=True は Werkzeug デバッガ経由の任意コード実行を許すため、
    # 既定では無効。SATIN_DASHBOARD_DEBUG=1 のときのみ有効化する。
    _debug = os.environ.get('SATIN_DASHBOARD_DEBUG') == '1'
    app.run(debug=_debug, port=_resolve_port())
