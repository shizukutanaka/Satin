import html as _html
import os
import json
from datetime import datetime
from functools import wraps

try:
    from mood import (
        get_mood_tracker as _get_mood_tracker,
        affinity_label,
        load_mood_history as _load_mood_history,
        _default_mood_history_path as _mood_history_path,
        mood_history_to_csv as _mood_history_to_csv,
    )
except Exception:
    _get_mood_tracker = None
    affinity_label = None
    _load_mood_history = None
    _mood_history_path = None
    _mood_history_to_csv = None

try:
    from daily_summary import daily_summary as _daily_summary, summary_greeting as _summary_greeting
except Exception:
    _daily_summary = None
    _summary_greeting = None

# 会話イベント分類は conversation_log を唯一の真実の源とする（集計の食い違い防止）。
try:
    from conversation_log import USER_EVENT_TYPES as _USER_TYPES, AVATAR_EVENT_TYPES as _AVATAR_TYPES
except Exception:
    _USER_TYPES = {"user_comment", "user"}
    _AVATAR_TYPES = {"avatar_reply", "avatar"}

try:
    from flask import Flask, render_template_string, request, redirect, url_for, send_file, session
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False
    Flask = render_template_string = request = redirect = url_for = send_file = session = None  # type: ignore

try:
    from i18n import I18N
except ImportError:
    from importlib.util import spec_from_file_location as _spec, module_from_spec as _mfs
    import os as _os
    _spec_obj = _spec("satin_i18n", _os.path.join(_os.path.dirname(__file__), "i18n.py"))
    _i18n_mod = _mfs(_spec_obj)
    _spec_obj.loader.exec_module(_i18n_mod)
    I18N = _i18n_mod.I18N

if _FLASK_AVAILABLE:
    app = Flask(__name__)
    # ハードコードされた秘密鍵はセッション/CSRF 偽造を許す。環境変数を優先し、
    # 未設定ならプロセス毎のランダム値にフォールバックする。
    app.secret_key = os.environ.get('SATIN_DASHBOARD_SECRET') or os.urandom(24).hex()
else:
    class _NoopApp:
        def route(self, *a, **kw): return lambda f: f
        secret_key = ""
    app = _NoopApp()  # type: ignore

event_log_path = 'avatar_event_log.jsonl'
backup_dir = 'event_report'


def _build_sync_backup(zip_path, config_dir, log_path):
    """設定一式（config/ 配下を再帰的に）と会話ログを zip にまとめる。

    旧実装は config/ 直下のファイルのみを対象にしており、config/plugins/*.json
    （i18n / logging / cache / performance / break_reminder の設定）が丸ごと
    バックアップから漏れていた。os.walk で再帰し全サブディレクトリを含める。

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
        if log_path and os.path.exists(log_path):
            arc = os.path.basename(log_path)
            zf.write(log_path, arc)
            written.append(arc)
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

def get_lang():
    lang = request.args.get('lang') or session.get('lang')
    if lang:
        session['lang'] = lang
        return lang
    return I18N().detect_language()

def with_lang(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        lang = get_lang()
        i18n = I18N(lang)
        return f(i18n, *args, **kwargs)
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
{% block content %}{% endblock %}
</body></html>
'''

@app.route('/')
@with_lang
def index(i18n):
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(en='selected' if lang=='en' else '', ja='selected' if lang=='ja' else '')
    # Build summary stats block
    stats_lines = []
    # Conversation count
    if os.path.exists(event_log_path):
        try:
            total = 0
            with open(event_log_path, encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        if ev.get('event_type') in _USER_TYPES:
                            total += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
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
    return render_template_string(TEMPLATE + '{% block content %}' + content + '{% endblock %}', i18n=i18n, lang=lang, switcher=switcher)

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
    return render_template_string(TEMPLATE + '{% block content %}' + content + '{% endblock %}', i18n=i18n, lang=lang, switcher=switcher)

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
    return render_template_string(TEMPLATE + '{% block content %}' + content + '{% endblock %}', i18n=i18n, lang=lang, switcher=switcher)

@app.route('/download/<fname>')
@with_lang
def download(i18n, fname):
    path = _safe_backup_path(fname)
    if path and os.path.isfile(path):
        return send_file(path, as_attachment=True)
    return i18n.t('no_file'), 404

@app.route('/sync', methods=['GET', 'POST'])
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
<form method="post"><button type="submit">{_html.escape(i18n.t("manual_cloud_sync"))}</button></form>
{backup_info}
<p style="color:{msg_color}">{_html.escape(msg)}</p>
{existing_html}'''
    return render_template_string(TEMPLATE + '{% block content %}' + content + '{% endblock %}', i18n=i18n, lang=lang, switcher=switcher)

@app.route('/conversation')
@with_lang
def conversation(i18n):
    """会話履歴のみを表示する（user_comment / avatar_reply イベントをフィルタ）。"""
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(
        en='selected' if lang.startswith('en') else '',
        ja='selected' if not lang.startswith('en') else '',
    )
    exchanges = []
    if os.path.exists(event_log_path):
        with open(event_log_path, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                    et = ev.get('event_type', '')
                    if et not in _USER_TYPES and et not in _AVATAR_TYPES:
                        continue
                    ts = datetime.fromtimestamp(ev['timestamp']).strftime('%H:%M:%S')
                    speaker = (
                        i18n.t('you', 'You') if et in _USER_TYPES
                        else i18n.t('avatar', 'Avatar')
                    )
                    details = ev.get('details') or {}
                    text = details.get('text', '') if isinstance(details, dict) else str(details)
                    exchanges.append({'ts': ts, 'speaker': speaker, 'text': text})
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    continue
    title = i18n.t('conversation', 'Chat History')
    content = f'<h3>{_html.escape(title)}</h3>'
    if not exchanges:
        content += f'<p>{_html.escape(i18n.t("no_conversation", "No conversation history yet."))}</p>'
    else:
        content += '<table border=0 cellpadding=6 cellspacing=2 style="width:100%">'
        for ex in exchanges[-100:]:
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
    csv_label = 'CSV' if lang.startswith('en') else 'CSV形式'
    content += (
        f'<p>'
        f'<a href="/conversation/download?lang={_html.escape(lang)}">'
        f'{_html.escape(i18n.t("download_conversation", "Download as text"))}</a>'
        f' &nbsp;|&nbsp; '
        f'<a href="/conversation/download/csv?lang={_html.escape(lang)}">'
        f'{_html.escape(csv_label)}</a>'
        f'</p>'
    )
    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


@app.route('/conversation/download')
@with_lang
def conversation_download(i18n):
    """会話履歴をプレーンテキストとしてダウンロードする。"""
    import io
    lines_out = []
    if os.path.exists(event_log_path):
        with open(event_log_path, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                    et = ev.get('event_type', '')
                    if et not in _USER_TYPES and et not in _AVATAR_TYPES:
                        continue
                    ts = datetime.fromtimestamp(ev['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    speaker = i18n.t('you', 'You') if et in _USER_TYPES else i18n.t('avatar', 'Avatar')
                    details = ev.get('details') or {}
                    text = details.get('text', '') if isinstance(details, dict) else str(details)
                    lines_out.append(f'[{ts}] {speaker}: {text}')
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
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
            avatar_label=i18n.t('avatar', 'Avatar'),
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
    <td>{_html.escape(label)} ({_html.escape(level)})</td></tr>
<tr><td><b>{_html.escape(i18n.t("interactions", "Interactions"))}</b></td>
    <td>{interactions}</td></tr>
<tr><td><b>{_html.escape(i18n.t("last_interaction", "Last interaction"))}</b></td>
    <td>{_html.escape(last_dt)}</td></tr>
</table>
<p>{history_link}</p>
<br>
<form method="post" action="/mood/reset?lang={_html.escape(lang)}">
  <button type="submit" onclick="return confirm('{reset_label}?')">
    {reset_label}
  </button>
</form>'''
        except Exception as exc:
            content = f'<h3>{i18n.t("mood", "Mood")}</h3><p>{_html.escape(str(exc))}</p>'
    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


@app.route('/mood/reset', methods=['POST'])
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
            if _default_mood_path is not None:
                tracker.save(_default_mood_path())
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
        q_lower = q.lower()
        matches = []
        if os.path.exists(event_log_path):
            with open(event_log_path, encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        et = ev.get('event_type', '')
                        if et not in _USER_TYPES and et not in _AVATAR_TYPES:
                            continue
                        details = ev.get('details') or {}
                        text = details.get('text', '') if isinstance(details, dict) else str(details)
                        if q_lower in text.lower():
                            ts = datetime.fromtimestamp(ev['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                            speaker = i18n.t('you', 'You') if et in _USER_TYPES else i18n.t('avatar', 'Avatar')
                            matches.append({'ts': ts, 'speaker': speaker, 'text': text})
                    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                        continue

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

    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


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
            content += f'<th></th>'
            content += f'<th>{_html.escape(i18n.t("affinity_level", "Level"))}</th></tr>'
            for e in entries:
                score = int(round(float(e.get("affinity", 0))))
                level = _html.escape(str(e.get("level", "")))
                date = _html.escape(str(e.get("date", "")))
                colour = f'hsl({int(score * 1.2)}, 70%, 45%)'
                bar_width = max(1, score * 2)
                content += (
                    f'<tr>'
                    f'<td>{date}</td>'
                    f'<td style="text-align:right">{score}</td>'
                    f'<td><div style="background:#ddd;width:200px;height:10px;display:inline-block;vertical-align:middle">'
                    f'<div style="background:{colour};width:{bar_width}px;height:10px"></div>'
                    f'</div></td>'
                    f'<td>{level}</td>'
                    f'</tr>'
                )
            content += '</table>'
        csv_lbl = 'Download CSV' if is_en else 'CSVダウンロード'
        content += (
            f'<p>'
            f'<a href="/mood?lang={_html.escape(lang)}">&larr; {_html.escape(i18n.t("back_to_mood", "Back to Mood"))}</a>'
            f' &nbsp;|&nbsp; '
            f'<a href="/mood/history/csv?lang={_html.escape(lang)}">{_html.escape(csv_lbl)}</a>'
            f'</p>'
        )

    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


def _conversation_stats(log_path: str) -> dict:
    """JSONL ログから会話統計を集計して辞書で返す（Flask 非依存）。

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
    total_user = 0
    total_avatar = 0
    per_day: dict = defaultdict(int)
    per_hour: dict = defaultdict(int)
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding='utf-8') as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        et = ev.get('event_type', '')
                        ts = ev.get('timestamp', 0)
                        if et in _USER_TYPES:
                            total_user += 1
                            dt = datetime.fromtimestamp(ts)
                            per_day[dt.strftime('%Y-%m-%d')] += 1
                            per_hour[dt.hour] += 1
                        elif et in _AVATAR_TYPES:
                            total_avatar += 1
                    except (json.JSONDecodeError, KeyError, ValueError, OSError, OverflowError):
                        continue
        except OSError:
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

    if is_en:
        content += f'<p>User messages: <b>{total_user}</b> &nbsp; Avatar replies: <b>{total_avatar}</b></p>'
    else:
        content += f'<p>ユーザーメッセージ: <b>{total_user}</b> &nbsp; アバター返答: <b>{total_avatar}</b></p>'

    if per_day:
        ph_label = 'Messages per day' if is_en else '日別メッセージ数'
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
        if is_en:
            content += f'<p>Peak activity: <b>{peak_hour:02d}:00–{peak_hour:02d}:59</b></p>'
        else:
            content += f'<p>ピーク時間帯: <b>{peak_hour:02d}:00–{peak_hour:02d}:59</b></p>'
        hr_label = 'Messages per hour' if is_en else '時間別メッセージ数'
        content += f'<h4>{_html.escape(hr_label)}</h4>'
        content += '<table border=0 cellpadding=2 cellspacing=2>'
        max_hr = max(per_hour.values()) if any(per_hour.values()) else 1
        for h in range(24):
            cnt = per_hour.get(h, 0)
            bar = max(0, int(cnt / max_hr * 120)) if max_hr else 0
            content += (
                f'<tr><td style="text-align:right;padding-right:4px">{h:02d}h</td>'
                f'<td style="text-align:right;padding-right:4px">{cnt}</td>'
                f'<td><div style="background:#5b9bd5;width:{bar}px;height:8px;display:inline-block"></div></td></tr>'
            )
        content += '</table>'

    if not per_day:
        no_data = 'No conversation data yet.' if is_en else 'まだ会話データがありません。'
        content += f'<p>{_html.escape(no_data)}</p>'

    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


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
        msg = 'Summary module unavailable.' if is_en else 'サマリー機能が利用できません。'
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

        date_lbl = 'Date' if is_en else '日付'
        user_lbl = 'Your messages' if is_en else 'あなたのメッセージ'
        avatar_lbl = 'Avatar replies' if is_en else 'アバターの返答'
        total_lbl = 'Total interactions' if is_en else '合計やりとり'
        peak_lbl = 'Peak hour' if is_en else 'ピーク時間帯'
        affinity_lbl = 'Affinity' if is_en else '好感度'

        peak = s['peak_hour']
        peak_str = f'{peak:02d}:00–{peak:02d}:59' if peak is not None else '—'
        affinity_str = (
            f'{s["affinity"]:.1f} ({_html.escape(str(s["affinity_level"]))})'
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

    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


if __name__ == '__main__':
    # debug=True は Werkzeug デバッガ経由の任意コード実行を許すため、
    # 既定では無効。SATIN_DASHBOARD_DEBUG=1 のときのみ有効化する。
    _debug = os.environ.get('SATIN_DASHBOARD_DEBUG') == '1'
    app.run(debug=_debug, port=5003)
