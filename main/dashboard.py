import os
import json
from flask import Flask, render_template_string, request, redirect, url_for, send_file, session
from datetime import datetime
from i18n import I18N

from functools import wraps

app = Flask(__name__)
app.secret_key = 'satin_dashboard_secret'

event_log_path = 'avatar_event_log.jsonl'
backup_dir = 'event_report'

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
                ev = json.loads(line)
                ts = datetime.fromtimestamp(ev['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                events.append({'ts': ts, 'type': ev['event_type'], 'details': ev['details']})
    content = f'<h3>{i18n.t("event_log")}</h3><table border=1 cellpadding=4><tr>' \
        f'<th>{i18n.t("time")}</th><th>{i18n.t("type")}</th><th>{i18n.t("details")}</th></tr>'
    for e in events[-100:]:
        content += f"<tr><td>{e['ts']}</td><td>{e['type']}</td><td>{e['details']}</td></tr>"
    content += '</table>'
    return render_template_string(TEMPLATE + '{% block content %}' + content + '{% endblock %}', i18n=i18n, lang=lang, switcher=switcher)

@app.route('/backups')
@with_lang
def backups(i18n):
    lang = get_lang()
    switcher = LANG_SWITCHER_HTML.format(en='selected' if lang=='en' else '', ja='selected' if lang=='ja' else '')
    files = [f for f in os.listdir(backup_dir) if f.endswith('.png') or f.endswith('.gz')]
    content = f'<h3>{i18n.t("backups")}</h3><ul>'
    for f in files:
        content += f'<li><a href="/download/{f}?lang={lang}">{f}</a></li>'
    content += '</ul>'
    return render_template_string(TEMPLATE + '{% block content %}' + content + '{% endblock %}', i18n=i18n, lang=lang, switcher=switcher)

@app.route('/download/<fname>')
@with_lang
def download(i18n, fname):
    path = os.path.join(backup_dir, fname)
    if os.path.exists(path):
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
    app.run(debug=True, port=5003)
