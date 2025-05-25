import os
import tkinter as tk
from tkinter import filedialog, messagebox, PhotoImage
from PIL import Image, ImageTk
import json

SUPPORTED_EXTS = [".vrm", ".fbx", ".glb", ".gltf"]
HISTORY_FILE = "avatar_history.json"
THUMBNAIL_SIZE = (80, 80)

class AvatarLoaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("外部アバター読み込み - Satin")
        self.avatar_path = tk.StringVar()
        tk.Label(root, text="アバターファイルを選択:").pack(padx=10, pady=5)
        entry = tk.Entry(root, textvariable=self.avatar_path, width=50)
        entry.pack(padx=10, pady=5)
        entry.drop_target_register('DND_Files')
        entry.dnd_bind('<<Drop>>', self.on_drop)
        tk.Button(root, text="ファイル選択", command=self.browse).pack(padx=10, pady=5)
        tk.Button(root, text="読み込み", command=self.load_avatar).pack(padx=10, pady=10)
        self.status = tk.Label(root, text="", fg="blue")
        self.status.pack(padx=10, pady=5)
        self.thumb_label = tk.Label(root)
        self.thumb_label.pack(padx=10, pady=5)
        tk.Label(root, text="最近使ったアバター:").pack(padx=10, pady=(15,2))
        self.history_list = tk.Listbox(root, width=60, height=3)
        self.history_list.pack(padx=10, pady=2)
        self.history_list.bind('<<ListboxSelect>>', self.select_history)
        self.load_history()

    def browse(self):
        f = filedialog.askopenfilename(
            title="アバターファイルを選択",
            filetypes=[("Avatar Files", "*.vrm *.fbx *.glb *.gltf")]
        )
        if f:
            self.avatar_path.set(f)
            self.show_thumbnail(f)

    def on_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        if files:
            self.avatar_path.set(files[0])
            self.show_thumbnail(files[0])

    def load_avatar(self):
        path = self.avatar_path.get()
        if not path or not os.path.isfile(path):
            messagebox.showerror("エラー", "有効なファイルを選択してください")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXTS:
            messagebox.showerror("エラー", f"対応拡張子: {', '.join(SUPPORTED_EXTS)}")
            return
        self.status.config(text=f"アバター読み込み成功: {os.path.basename(path)}", fg="green")
        self.show_thumbnail(path)
        self.add_history(path)
        print(f"[INFO] Avatar loaded: {path}")

    def show_thumbnail(self, path):
        ext = os.path.splitext(path)[1].lower()
        thumb = None
        if ext in [".png", ".jpg", ".jpeg"]:
            try:
                img = Image.open(path)
                img.thumbnail(THUMBNAIL_SIZE)
                thumb = ImageTk.PhotoImage(img)
            except Exception:
                thumb = None
        if thumb:
            self.thumb_label.config(image=thumb)
            self.thumb_label.image = thumb
        else:
            self.thumb_label.config(image='', text='[No Preview]')

    def load_history(self):
        self.history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, encoding='utf-8') as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []
        self.update_history_list()

    def add_history(self, path):
        if path in self.history:
            self.history.remove(path)
        self.history.insert(0, path)
        self.history = self.history[:5]
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False)
        self.update_history_list()

    def update_history_list(self):
        self.history_list.delete(0, tk.END)
        for h in self.history:
            self.history_list.insert(tk.END, h)

    def select_history(self, event):
        sels = self.history_list.curselection()
        if sels:
            path = self.history_list.get(sels[0])
            self.avatar_path.set(path)
            self.show_thumbnail(path)

if __name__ == "__main__":
    try:
        import tkinterdnd2 as tkdnd
        tk.Tk = tkdnd.TkinterDnD.Tk
    except ImportError:
        pass
    root = tk.Tk()
    app = AvatarLoaderApp(root)
    root.mainloop()
