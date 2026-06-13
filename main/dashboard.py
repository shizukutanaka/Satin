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
    )
except Exception:
    _get_mood_tracker = None
    affinity_label = None
    _load_mood_history = None
    _mood_history_path = None

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
  <li><a href="/backups?lang={{lang}}">{{i18n.t('backups')}}</a></li>
  <li><a href="/sync?lang={{lang}}">{{i18n.t('cloud_sync')}}</a></li>
  <li><a href="/mood?lang={{lang}}">{{i18n.t('mood', 'Mood')}}</a></li>
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
                        if ev.get('event_type') in ('user_comment', 'user'):
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
        files = [f for f in os.listdir(backup_dir) if f.endswith('.png') or f.endswith('.gz')]
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
    if request.method == 'POST':
        msg = i18n.t('executed_cloud_sync')
    content = f'''<h3>{i18n.t("cloud_sync")}</h3>
    <form method="post"><button type="submit">{i18n.t('manual_cloud_sync')}</button></form>
    <p style="color:green">{msg}</p>'''
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
    _USER_TYPES = {"user_comment", "user"}
    _AVATAR_TYPES = {"avatar_reply", "avatar"}
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
    content += f'<p><a href="/conversation/download?lang={_html.escape(lang)}">{_html.escape(i18n.t("download_conversation", "Download as text"))}</a></p>'
    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


@app.route('/conversation/download')
@with_lang
def conversation_download(i18n):
    """会話履歴をプレーンテキストとしてダウンロードする。"""
    import io
    _USER_TYPES = {"user_comment", "user"}
    _AVATAR_TYPES = {"avatar_reply", "avatar"}
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
        content += f'<p><a href="/mood?lang={_html.escape(lang)}">&larr; {_html.escape(i18n.t("back_to_mood", "Back to Mood"))}</a></p>'

    return render_template_string(
        TEMPLATE + '{% block content %}' + content + '{% endblock %}',
        i18n=i18n, lang=lang, switcher=switcher,
    )


if __name__ == '__main__':
    # debug=True は Werkzeug デバッガ経由の任意コード実行を許すため、
    # 既定では無効。SATIN_DASHBOARD_DEBUG=1 のときのみ有効化する。
    _debug = os.environ.get('SATIN_DASHBOARD_DEBUG') == '1'
    app.run(debug=_debug, port=5003)
