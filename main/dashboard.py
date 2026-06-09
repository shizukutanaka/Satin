import html as _html
import os
import json
from datetime import datetime
from functools import wraps

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
  <li><a href="/backups?lang={{lang}}">{{i18n.t('backups')}}</a></li>
  <li><a href="/sync?lang={{lang}}">{{i18n.t('cloud_sync')}}</a></li>
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
    return render_template_string(TEMPLATE, i18n=i18n, lang=lang, switcher=switcher)

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

if __name__ == '__main__':
    # debug=True は Werkzeug デバッガ経由の任意コード実行を許すため、
    # 既定では無効。SATIN_DASHBOARD_DEBUG=1 のときのみ有効化する。
    _debug = os.environ.get('SATIN_DASHBOARD_DEBUG') == '1'
    app.run(debug=_debug, port=5003)
