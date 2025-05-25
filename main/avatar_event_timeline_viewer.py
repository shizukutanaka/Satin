import sys
import json
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow, QListWidget, QLabel, QVBoxLayout, QWidget, QFileDialog
from PyQt5.QtCore import Qt

class EventTimelineViewer(QMainWindow):
    def __init__(self, logfile="avatar_event_log.jsonl"):
        super().__init__()
        self.setWindowTitle("アバターイベントタイムラインビューア")
        self.resize(700, 500)
        self.logfile = logfile
        self.events = []
        self.list_widget = QListWidget()
        self.detail_label = QLabel("イベント詳細")
        self.detail_label.setWordWrap(True)
        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)
        layout.addWidget(self.detail_label)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.list_widget.currentRowChanged.connect(self.show_detail)
        self.load_logfile(self.logfile)
        # メニューバーでログファイル切替
        menubar = self.menuBar()
        filemenu = menubar.addMenu("ファイル")
        openact = filemenu.addAction("ログファイルを開く...")
        openact.triggered.connect(self.open_logfile)

    def open_logfile(self):
        path, _ = QFileDialog.getOpenFileName(self, "ログファイル選択", "", "JSON Lines (*.jsonl);;All Files (*)")
        if path:
            self.load_logfile(path)

    def load_logfile(self, path):
        self.events.clear()
        self.list_widget.clear()
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    ev = json.loads(line)
                    self.events.append(ev)
            for ev in self.events:
                ts = datetime.fromtimestamp(ev["timestamp"]).strftime("%m-%d %H:%M:%S")
                etype = ev["event_type"]
                summary = f"[{ts}] {etype}"
                self.list_widget.addItem(summary)
        except Exception as e:
            self.detail_label.setText(f"ログ読込エラー: {e}")

    def show_detail(self, idx):
        if 0 <= idx < len(self.events):
            ev = self.events[idx]
            details = json.dumps(ev["details"], ensure_ascii=False, indent=2)
            ts = datetime.fromtimestamp(ev["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            self.detail_label.setText(f"<b>時刻:</b> {ts}<br><b>種別:</b> {ev['event_type']}<br><b>詳細:</b><pre>{details}</pre>")
        else:
            self.detail_label.setText("")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = EventTimelineViewer()
    viewer.show()
    sys.exit(app.exec_())
