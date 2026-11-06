# -*- coding: utf-8 -*-
"""
StarTrace · 图形界面（Win11 风格：圆角卡片 + 胶囊按钮）
作者 Guozhengkun · v1.0.0
"""

import ctypes
import datetime
import queue
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import mailer_core as core
from system_tray import WindowsTrayIcon

# ---------- Win11 主题 ----------
BG = "#F3F3F3"           # 窗口浅灰底
CARD = "#FFFFFF"         # 卡片白
BORDER = "#E6E6E6"       # 卡片描边
TEXT = "#1F1F1F"
SUB = "#6E6E6E"
ACCENT = "#0067C0"       # Win11 蓝
ACCENT_HOVER = "#1975C6"
ACCENT_PRESS = "#005FB0"
ACCENT_BG = "#E8F1FA"
GREEN = "#107C10"
GREEN_HOVER = "#0E6B0E"
RED = "#C42B1C"
DARK = "#24292F"         # GitHub 深色
DARK_SUB = "#9AA4AF"
FIELD = "#FBFBFB"

FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI Semibold", 17)
FONT_SUB = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)

LANGS = ["all", "python", "javascript", "typescript", "go", "rust", "java", "c++",
         "c#", "php", "swift", "kotlin", "ruby", "dart", "shell", "html", "css",
         "vue", "jupyter-notebook", "assembly", "lua", "perl", "haskell", "elixir",
         "scala", "objective-c", "r", "zig", "nim"]


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class PillButton(tk.Canvas):
    """Win11 风格胶囊按钮（Canvas 绘制，带悬停/按下反馈）。"""

    PALETTE = {
        "primary":   (ACCENT, ACCENT_HOVER, ACCENT_PRESS, "#FFFFFF"),
        "secondary": ("#FFFFFF", "#F0F0F0", "#E3E3E3", TEXT),
        "success":   (GREEN, GREEN_HOVER, "#0C5F0C", "#FFFFFF"),
        "danger":    ("#FFFFFF", "#FDEBEA", "#F8D7D5", RED),
    }

    def __init__(self, master, text, command=None, kind="primary", width=None,
                 height=36, font=FONT_B, padx=22, state="normal"):
        self._text = text
        self._command = command
        self._kind = kind
        self._font = font
        self._padx = padx
        self._state = state
        bg = master.cget("bg")
        w = width or (self._measure(text) + padx * 2)
        super().__init__(master, width=w, height=height, highlightthickness=0,
                         bg=bg, cursor="hand2")
        self.bind("<Enter>", lambda e: self._draw("hover"))
        self.bind("<Leave>", lambda e: self._draw("normal"))
        self.bind("<ButtonPress-1>", lambda e: self._draw("press"))
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw("normal")

    def _measure(self, text):
        f = tkfont.Font(family=self._font[0], size=self._font[1],
                        weight=self._font[2] if len(self._font) > 2 else "normal")
        return f.measure(text)

    def _colors(self):
        return self.PALETTE[self._kind]

    def _draw(self, state):
        self.delete("all")
        fill, hover, press, fg = self._colors()
        if self._state != "normal":
            fill = hover = press = "#E0E0E0"
            fg = "#A0A0A0"
        elif state == "hover":
            fill = hover
        elif state == "press":
            fill = press
        w = int(self["width"])
        h = int(self["height"])
        if self._kind in ("secondary", "danger"):
            round_rect(self, 0, 0, w, h, h // 2, fill=fill, outline=BORDER, width=1)
        else:
            round_rect(self, 0, 0, w, h, h // 2, fill=fill, outline=fill)
        self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=self._font)

    def _on_release(self, _e):
        self._draw("normal")
        if self._state == "normal" and self._command:
            self._command()

    def set_state(self, state):
        self._state = state
        self._draw("normal")

    def set_text(self, text):
        self._text = text
        self.config(width=self._measure(text) + self._padx * 2)
        self._draw("normal")


class Card(tk.Canvas):
    """圆角卡片容器：Canvas 绘制圆角白卡，inner 为内容区。"""

    def __init__(self, master, pad=18, radius=12, fill=CARD, outline=BORDER, bg=BG):
        super().__init__(master, highlightthickness=0, bg=bg)
        self._fill, self._outline, self._radius, self._pad = fill, outline, radius, pad
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.inner)
        self.inner.bind("<Configure>", self._sync)
        self.bind("<Configure>", self._redraw_bg)
        self._redraw_bg()

    def _redraw_bg(self, _e=None):
        self.delete("bg")
        w, h = self.winfo_width(), self.winfo_height()
        if w > 20 and h > 20:
            self.itemconfigure(self._win, width=max(1, w - self._pad * 2))
            round_rect(self, 0, 0, w, h, self._radius,
                       fill=self._fill, outline=self._outline, tags="bg")
            self.tag_lower("bg")

    def _sync(self, e):
        self.config(height=e.height + self._pad * 2)


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        core.attach_log_queue(self.q)
        self.busy = False
        self.dirty = False
        self._toast = None
        self._toast_after = None
        self._action_buttons = []
        self.tray = None
        self._build()
        self._load_cfg_to_ui()
        self.root.after(100, self._poll)
        self.root.after(300, self._refresh_task_status)

    # ---------- 界面搭建 ----------
    def _build(self):
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=22, pady=18)

        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", pady=(0, 28))
        brand = tk.Frame(header, bg=BG, cursor="hand2")
        brand.pack(anchor="w")
        title_group = tk.Frame(brand, bg=BG, cursor="hand2")
        title_group.pack(side="left")
        title = tk.Label(title_group, text=core.APP_NAME, font=FONT_TITLE, fg=TEXT,
                         bg=BG, cursor="hand2")
        title.pack(anchor="w")
        tk.Label(title_group, text="每天发现值得关注的 GitHub 项目",
                 font=FONT_SMALL, fg=SUB, bg=BG).pack(anchor="w", pady=(1, 0))
        for widget in (brand, title_group, title):
            widget.bind("<Button-1>", self._show_about)

        tabs = ttk.Notebook(main)
        tabs.pack(fill="both", expand=True)
        style = ttk.Style(self.root)
        style.configure("TNotebook.Tab", padding=(18, 10), font=FONT)
        home = tk.Frame(tabs, bg=BG)
        settings = tk.Frame(tabs, bg=BG)
        tabs.add(home, text="今日项目")
        tabs.add(settings, text="设置")

        settings_canvas = tk.Canvas(settings, bg=BG, highlightthickness=0)
        settings_scroll = ttk.Scrollbar(settings, orient="vertical", command=settings_canvas.yview)
        settings_canvas.configure(yscrollcommand=settings_scroll.set)
        settings_scroll.pack(side="right", fill="y")
        settings_canvas.pack(side="left", fill="both", expand=True)
        settings_body = tk.Frame(settings_canvas, bg=BG)
        settings_window = settings_canvas.create_window((0, 0), window=settings_body, anchor="nw")
        settings_body.bind("<Configure>", lambda _e: settings_canvas.configure(
            scrollregion=settings_canvas.bbox("all")))
        settings_canvas.bind("<Configure>", lambda e: settings_canvas.itemconfigure(
            settings_window, width=e.width))

        home_inner = tk.Frame(home, bg=BG)
        home_inner.pack(fill="both", expand=True, padx=28, pady=30)
        home_top = tk.Frame(home_inner, bg=BG)
        home_top.pack(fill="x")
        tk.Label(home_top, text="项目预览", font=FONT_SUB, fg=TEXT, bg=BG).pack(side="left")
        self.task_label = tk.Label(home_top, text="检查定时推送…", font=FONT_SMALL, fg=SUB, bg=BG)
        self.task_label.pack(side="right")

        home_actions = tk.Frame(home_inner, bg=BG)
        home_actions.pack(fill="x", pady=(24, 20))
        preview_btn = PillButton(home_actions, "获取今日项目", self.on_preview, "primary")
        send_btn = PillButton(home_actions, "立即发送", self.on_send, "secondary")
        enable_btn = PillButton(home_actions, "开启每日推送", self.on_enable_task, "secondary")
        preview_btn.pack(side="left", padx=(0, 12))
        send_btn.pack(side="left", padx=(0, 12))
        enable_btn.pack(side="left")
        self.home_status = tk.Label(home_inner, text="", font=FONT_SMALL, fg=SUB, bg=BG, anchor="w")
        self.home_status.pack(fill="x", pady=(0, 16))

        self.progress_frame = tk.Frame(home_inner, bg=BG)
        progress_top = tk.Frame(self.progress_frame, bg=BG)
        progress_top.pack(fill="x", pady=(0, 6))
        self.progress_label = tk.Label(progress_top, text="", font=FONT_SMALL,
                                       fg=SUB, bg=BG, anchor="w")
        self.progress_label.pack(side="left", fill="x", expand=True)
        self.progress_percent = tk.Label(progress_top, text="", font=FONT_SMALL,
                                         fg=ACCENT, bg=BG, anchor="e")
        self.progress_percent.pack(side="right")
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode="determinate",
                                            maximum=100, style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x")
        self.progress_frame.pack_forget()

        preview_wrap = tk.Frame(home_inner, bg=CARD, highlightthickness=1,
                                highlightbackground=BORDER)
        preview_wrap.pack(fill="both", expand=True)
        self.preview_text = tk.Text(preview_wrap, wrap="word", relief="flat", borderwidth=0,
                                    bg=CARD, fg=TEXT, font=FONT, padx=30, pady=26,
                                    state="disabled")
        preview_scroll = ttk.Scrollbar(preview_wrap, command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=preview_scroll.set)
        self.preview_text.pack(side="left", fill="both", expand=True)
        preview_scroll.pack(side="right", fill="y")
        self.preview_text.tag_configure("heading", font=FONT_B, spacing1=22, spacing3=9)
        self.preview_text.tag_configure("meta", foreground=SUB, font=FONT_SMALL, spacing3=12)
        self.preview_text.tag_configure("description", foreground=TEXT, lmargin1=16,
                                        lmargin2=16, spacing3=14)
        self.preview_text.tag_configure("link", foreground=ACCENT, lmargin1=16,
                                        lmargin2=16, spacing3=14)
        self._render_preview_message("选择“获取今日项目”查看榜单预览。")

        # 邮箱设置卡
        mail_card = Card(settings_body, pad=24)
        mail_card.pack(fill="x", padx=22, pady=(24, 0))
        mc = mail_card.inner
        self._section_title(mc, "✉", "邮件账户").pack(anchor="w")
        self.var_smtp_host = self._entry_row(mc, "SMTP 服务器", "smtp.qq.com", width=22)
        self.var_smtp_port = self._entry_row(mc, "端口", "465", width=7)
        self.var_sender = self._entry_row(mc, "发件邮箱", "例如 123456@qq.com", width=28)
        self.var_auth = tk.StringVar()
        self.var_show_auth = tk.BooleanVar(value=False)
        self.auth_entry = self._secret_row(
            mc, "SMTP 授权码", "使用邮箱服务商提供的 SMTP 授权码",
            self.var_auth, self.var_show_auth)
        self.var_to = self._entry_row(mc, "收件邮箱", "可填多个，用逗号分隔", width=34)

        # 推送设置卡
        set_card = Card(settings_body, pad=24)
        set_card.pack(fill="x", padx=22, pady=(22, 0))
        sc = set_card.inner
        self._section_title(sc, "⚙", "日报与推送").pack(anchor="w", pady=(0, 6))
        row = tk.Frame(sc, bg=CARD)
        row.pack(fill="x")
        self._settings_group(row, "项目语言", 0)
        self._settings_group(row, "推送数量（条）", 1)
        self._settings_group(row, "每天推送时间", 2)
        self.var_include_chinese = tk.BooleanVar(value=True)

        translation_card = Card(settings_body, pad=22)
        translation_card.pack(fill="x", padx=22, pady=(22, 0))
        tc = translation_card.inner
        self._section_title(tc, "☁", "中文简介与翻译").pack(anchor="w")
        tk.Checkbutton(tc, text="在日报中附加中文简介",
                       variable=self.var_include_chinese, command=self._on_translation_change,
                       bg=CARD, fg=TEXT, activebackground=CARD, selectcolor=CARD,
                       font=FONT).pack(anchor="w", pady=(10, 2))
        tk.Label(tc, text="默认开启；关闭后日报仅显示英文原文。",
                 bg=CARD, fg=SUB, font=FONT_SMALL).pack(anchor="w", padx=(26, 0))

        self.var_provider = tk.StringVar(value="local")
        provider_options = tk.Frame(tc, bg=CARD)
        provider_options.pack(fill="x", pady=(12, 0))
        local_option = tk.Frame(provider_options, bg=CARD)
        local_option.pack(fill="x", pady=(0, 6))
        tk.Radiobutton(local_option, text="本地模型", value="local", variable=self.var_provider,
                       command=self._on_translation_change, bg=CARD, fg=TEXT,
                       activebackground=CARD, selectcolor=CARD, font=FONT_B).pack(anchor="w")
        tk.Label(local_option, text="无需 API 密钥；模型下载后可离线翻译。",
                 bg=CARD, fg=SUB, font=FONT_SMALL).pack(anchor="w", padx=(26, 0))
        cloud_option = tk.Frame(provider_options, bg=CARD)
        cloud_option.pack(fill="x", pady=(5, 0))
        tk.Radiobutton(cloud_option, text="云大模型", value="remote", variable=self.var_provider,
                       command=self._on_translation_change, bg=CARD, fg=TEXT,
                       activebackground=CARD, selectcolor=CARD, font=FONT_B).pack(anchor="w")
        tk.Label(cloud_option, text="使用你自己的兼容 API 账户，速度和效果取决于所选模型。",
                 bg=CARD, fg=SUB, font=FONT_SMALL).pack(anchor="w", padx=(26, 0))

        self.api_fields = tk.Frame(tc, bg=CARD)
        self.var_api_url = self._entry_row(
            self.api_fields, "API 地址", "阿里百炼示例：https://dashscope.aliyuncs.com/compatible-mode/v1", width=42)
        self.var_api_model = self._entry_row(self.api_fields, "模型名称", "例如 qwen-plus", width=24)
        self.var_api_key = tk.StringVar()
        self._secret_row(self.api_fields, "API Key", "密钥仅保存在本机凭据管理器", self.var_api_key)
        self.var_api_key.trace_add("write", lambda *_: self._mark_dirty())

        self.local_fields = tk.Frame(tc, bg=CARD)
        model_note = tk.Label(
            self.local_fields, text="Index-Translate 2B 本地模型约 1.31 GB，建议预留 4 GB 可用内存；优先使用 ModelScope 国内源。",
            bg=CARD, fg=SUB, font=FONT_SMALL, justify="left", wraplength=640)
        model_note.pack(anchor="w", pady=(8, 0))
        self.local_fields.bind("<Configure>", lambda e: model_note.configure(wraplength=max(220, e.width - 4)))
        model_controls = tk.Frame(self.local_fields, bg=CARD)
        model_controls.pack(fill="x", pady=(12, 0))
        self.model_status = tk.Label(
            model_controls,
            text="翻译模型：已下载" if core.translation_model_ready() else "翻译模型：尚未下载",
            bg=CARD, fg=GREEN if core.translation_model_ready() else SUB, font=FONT_SMALL)
        self.model_status.pack(side="left")
        model_btn = PillButton(model_controls, "下载并准备翻译模型",
                               self.on_prepare_model, "secondary", height=32, padx=16)
        model_btn.pack(side="right")
        self._update_translation_ui()

        settings_actions = tk.Frame(settings_body, bg=BG)
        settings_actions.pack(fill="x", padx=22, pady=(22, 0))
        save_btn = PillButton(settings_actions, "保存设置", self.on_save, "primary")
        reset_btn = PillButton(settings_actions, "重置未保存修改", self.on_reset, "secondary")
        disable_btn = PillButton(settings_actions, "取消每日推送", self.on_disable_task, "secondary")
        save_btn.pack(side="left", padx=(0, 8))
        reset_btn.pack(side="left", padx=(0, 8))
        disable_btn.pack(side="left")
        self._action_buttons = [preview_btn, send_btn, enable_btn, save_btn,
                                reset_btn, disable_btn, model_btn]

        # 运行记录留在设置页，避免首页被技术日志占据。
        log_card = Card(settings_body, pad=18)
        log_card.pack(fill="x", padx=22, pady=(22, 24))
        lc = log_card.inner
        top = tk.Frame(lc, bg=CARD)
        top.pack(fill="x")
        self._section_title(top, "≡", "运行记录").pack(side="left")
        log_area = tk.Frame(lc, bg=CARD)
        log_area.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(log_area, height=6, wrap="word", relief="flat",
                                bg="#FAFAFA", fg=TEXT, font=FONT_MONO,
                                highlightthickness=1, highlightbackground=BORDER,
                                highlightcolor=BORDER, state="disabled")
        sb = ttk.Scrollbar(log_area, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("err", foreground=RED)
        self.log_text.tag_configure("info", foreground=SUB)
        self.log_text.tag_configure("head", foreground=TEXT)
        self.log_text.tag_configure("line", foreground=ACCENT)

        # 底部
        footer = tk.Frame(main, bg=BG)
        footer.pack(fill="x", pady=(10, 0))
        tk.Label(footer, text=core.APP_NAME,
                 font=FONT_SMALL, fg=SUB, bg=BG).pack(side="left")
        PillButton(footer, "打开所在文件夹", self.on_open_dir, "secondary",
                   height=30, font=FONT_SMALL, padx=14).pack(side="right")
        PillButton(footer, "查看日志文件", self.on_open_log, "secondary",
                   height=30, font=FONT_SMALL, padx=14).pack(side="right", padx=(0, 8))

        self._bind_settings_scroll(settings, settings_canvas)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _entry_row(self, parent, label, hint, width=24, show=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(12, 0))
        var = tk.StringVar()
        var.trace_add("write", lambda *a: self._mark_dirty())
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT,
                 width=12, anchor="nw").grid(row=0, column=0, rowspan=2, sticky="nw", pady=(5, 0))
        row.grid_columnconfigure(1, weight=1)
        tk.Entry(row, textvariable=var, width=width, show=show, relief="flat",
                 font=FONT, bg=FIELD, fg=TEXT, insertbackground=TEXT,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).grid(row=0, column=1,
                                             sticky="ew" if width > 10 else "w", ipady=4)
        hint_label = tk.Label(row, text=hint, bg=CARD, fg=SUB, font=FONT_SMALL,
                              anchor="w", justify="left", wraplength=520)
        hint_label.grid(row=1, column=1, sticky="ew", pady=(3, 0))
        row.bind("<Configure>", lambda e: hint_label.configure(wraplength=max(160, e.width - 112)))
        return var

    def _secret_row(self, parent, label, hint, variable, visible_var=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(12, 0))
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT,
                 width=12, anchor="nw").grid(row=0, column=0, rowspan=2, sticky="nw", pady=(5, 0))
        row.grid_columnconfigure(1, weight=1)
        controls = tk.Frame(row, bg=CARD)
        controls.grid(row=0, column=1, sticky="ew")
        controls.grid_columnconfigure(0, weight=1)
        entry = tk.Entry(controls, textvariable=variable, show="●", relief="flat",
                         font=FONT, bg=FIELD, fg=TEXT, insertbackground=TEXT,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
        entry.grid(row=0, column=0, sticky="ew", ipady=4)
        if visible_var is None:
            visible_var = tk.BooleanVar(value=False)
        tk.Checkbutton(controls, text="显示", variable=visible_var,
                       command=lambda: entry.configure(show="" if visible_var.get() else "●"),
                       bg=CARD, fg=SUB, activebackground=CARD, font=FONT_SMALL,
                       selectcolor=CARD, highlightthickness=0).grid(row=0, column=1, padx=(8, 0))
        hint_label = tk.Label(row, text=hint, bg=CARD, fg=SUB, font=FONT_SMALL,
                              anchor="w", justify="left", wraplength=520)
        hint_label.grid(row=1, column=1, sticky="ew", pady=(3, 0))
        row.bind("<Configure>", lambda e: hint_label.configure(wraplength=max(160, e.width - 112)))
        return entry

    @staticmethod
    def _section_title(parent, icon, title):
        heading = tk.Frame(parent, bg=CARD)
        badge = tk.Label(heading, text=icon, bg=ACCENT_BG, fg=ACCENT,
                         font=("Segoe UI Symbol", 12, "bold"), width=3, pady=3)
        badge.pack(side="left", padx=(0, 10))
        tk.Label(heading, text=title, bg=CARD, fg=TEXT, font=FONT_B).pack(side="left")
        return heading

    @staticmethod
    def _bind_settings_scroll(widget, canvas):
        def scroll(event):
            if getattr(event, "num", None) == 4:
                amount = -3
            elif getattr(event, "num", None) == 5:
                amount = 3
            else:
                delta = getattr(event, "delta", 0)
                amount = -max(1, abs(int(delta / 120))) * (1 if delta > 0 else -1)
            canvas.yview_scroll(amount, "units")
            return "break"

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, scroll, add="+")
        for child in widget.winfo_children():
            App._bind_settings_scroll(child, canvas)

    def _on_translation_change(self):
        self._mark_dirty()
        self._update_translation_ui()

    def _update_translation_ui(self):
        if not hasattr(self, "api_fields"):
            return
        if self.var_provider.get() == "remote":
            self.local_fields.pack_forget()
            self.api_fields.pack(fill="x", pady=(10, 0))
        else:
            self.api_fields.pack_forget()
            self.local_fields.pack(fill="x", pady=(10, 0))

    def _settings_group(self, parent, label, col):
        grp = tk.Frame(parent, bg=CARD)
        grp.grid(row=0, column=col, sticky="ew", padx=(0, 12), pady=(8, 4))
        parent.grid_columnconfigure(col, weight=1)
        tk.Label(grp, text=label, bg=CARD, fg=SUB, font=FONT_SMALL).pack(anchor="w")
        if col == 0:
            self.var_lang = tk.StringVar(value="all")
            cb = ttk.Combobox(grp, textvariable=self.var_lang, values=LANGS,
                              width=16, state="readonly", font=FONT)
            cb.pack(anchor="w", pady=(4, 0))
            cb.bind("<<ComboboxSelected>>", lambda *a: self._mark_dirty())
        elif col == 1:
            self.var_topn = tk.StringVar(value="25")
            sp = tk.Spinbox(grp, from_=5, to=50, textvariable=self.var_topn, width=8,
                            relief="flat", font=FONT, bg=FIELD, fg=TEXT,
                            buttonbackground="#F0F0F0", highlightthickness=1,
                            highlightbackground=BORDER, highlightcolor=ACCENT)
            sp.pack(anchor="w", pady=(4, 0), ipady=2)
            self.var_topn.trace_add("write", lambda *a: self._mark_dirty())
        else:
            self.var_time = tk.StringVar(value="09:00")
            te = tk.Entry(grp, textvariable=self.var_time, width=8, relief="flat",
                          font=FONT, bg=FIELD, fg=TEXT, insertbackground=TEXT,
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=ACCENT)
            te.pack(anchor="w", pady=(4, 0), ipady=4)
            te.bind("<Return>", lambda e: self.on_save())
            self.var_time.trace_add("write", lambda *a: self._mark_dirty())

    def _toggle_auth(self):
        self.auth_entry.config(show="" if self.var_show_auth.get() else "●")

    def _show_about(self, _event=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"关于 {core.APP_NAME}")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.configure(bg=BG)
        # Toplevels otherwise display Tk's default feather icon on Windows.
        # Reuse the StarTrace application icon in the title bar.
        try:
            window_icon = Path(getattr(sys, "_MEIPASS", core.BASE_DIR)) / "app.ico"
            if not window_icon.exists():
                window_icon = core.BASE_DIR / "app.ico"
            if window_icon.exists():
                dialog.iconbitmap(str(window_icon))
        except Exception:
            pass
        width, height = 620, 470
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.minsize(460, 410)

        content = tk.Frame(dialog, bg=CARD, highlightthickness=1,
                           highlightbackground=BORDER)
        content.pack(fill="both", expand=True, padx=18, pady=18)
        hero = tk.Frame(content, bg=CARD)
        hero.pack(fill="x", padx=24, pady=(24, 20))
        icon_path = Path(getattr(sys, "_MEIPASS", core.BASE_DIR)) / "trace.png"
        if not icon_path.exists():
            icon_path = core.BASE_DIR / "trace.png"
        try:
            avatar = tk.PhotoImage(file=str(icon_path))
            shrink = max(1, (max(avatar.width(), avatar.height()) + 95) // 96)
            self._about_avatar = avatar.subsample(shrink, shrink)
            tk.Label(hero, image=self._about_avatar, bg=CARD,
                     highlightthickness=1, highlightbackground=BORDER).pack(side="left", padx=(0, 18))
        except Exception:
            fallback = tk.Label(hero, text="G", bg=ACCENT_BG, fg=ACCENT,
                                font=("Segoe UI Semibold", 28), width=3, height=2)
            fallback.pack(side="left", padx=(0, 18))
        identity = tk.Frame(hero, bg=CARD)
        identity.pack(side="left", fill="both", expand=True, pady=3)
        title_label = tk.Label(identity, text=core.APP_NAME, font=("Segoe UI Semibold", 20),
                               fg=TEXT, bg=CARD, anchor="w")
        title_label.pack(anchor="w", fill="x")
        tagline = tk.Label(identity, text="GitHub 热门项目，每日为你整理",
                           font=FONT_SMALL, fg=SUB, bg=CARD, anchor="w", justify="left")
        tagline.pack(anchor="w", fill="x", pady=(2, 0))
        identity.bind("<Configure>", lambda e: tagline.configure(wraplength=max(140, e.width)))
        tk.Label(hero, text=core.APP_VERSION, font=FONT_SMALL, fg=ACCENT,
                 bg=ACCENT_BG, padx=10, pady=5).pack(side="right", anchor="n", padx=(8, 0))

        tk.Frame(content, bg=BORDER, height=1).pack(fill="x", padx=24)
        details = tk.Frame(content, bg=CARD)
        details.pack(fill="both", expand=True, padx=28, pady=(16, 12))
        value_labels = []
        for label, value in (("作者", core.APP_AUTHOR), ("邮箱", "guozhengkun@tju.edu.cn"),
                             ("数据来源", "GitHub Trending")):
            row = tk.Frame(details, bg=CARD)
            row.pack(fill="x", pady=7)
            tk.Label(row, text=label, font=FONT_SMALL, fg=SUB, bg=CARD,
                     width=10, anchor="nw").pack(side="left")
            value_label = tk.Label(row, text=value, font=FONT, fg=TEXT, bg=CARD,
                                   anchor="w", justify="left", wraplength=420)
            value_label.pack(side="left", fill="x", expand=True)
            value_labels.append(value_label)
        details.bind("<Configure>", lambda e: [
            label.configure(wraplength=max(180, e.width - 105)) for label in value_labels])
        tk.Label(content, text="愿每一次发现，都能带来一点灵感。",
                 font=FONT_SMALL, fg=SUB, bg=CARD).pack(anchor="w", padx=28, pady=(0, 14))
        actions = tk.Frame(content, bg=CARD)
        actions.pack(fill="x", padx=24, pady=(0, 18))
        PillButton(actions, "好的", dialog.destroy, "primary", width=96,
                   height=34, padx=18).pack(side="right")
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.grab_set()
        dialog.focus_set()

    def start_tray(self, icon_path):
        if sys.platform == "win32":
            self.tray = WindowsTrayIcon(icon_path, self._tray_action, core.APP_NAME)
            if self.tray.error:
                self.log(f"⚠ 系统托盘图标启动失败：{self.tray.error}", "err")

    def _tray_action(self, action):
        self.root.after(0, lambda: self._handle_tray_action(action))

    def _handle_tray_action(self, action):
        if action == "open":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        elif action == "send":
            self.root.deiconify()
            self.root.lift()
            self.on_send()
        elif action == "exit":
            self._exit_app()

    # ---------- 配置读写 ----------
    def _load_cfg_to_ui(self):
        cfg = core.read_config()
        smtp = cfg.get("smtp") or {}
        self.var_smtp_host.set(str(smtp.get("host", "smtp.qq.com")))
        self.var_smtp_port.set(str(smtp.get("port", 465)))
        self.var_sender.set(str(smtp.get("user", "")))
        self.var_auth.set(str(smtp.get("auth_code", "")))
        to = cfg.get("to") or []
        if isinstance(to, str):
            to = [to]
        self.var_to.set(", ".join(str(x) for x in to))
        self.var_lang.set(str(cfg.get("language", "all")))
        self.var_topn.set(str(cfg.get("top_n", 25)))
        self.var_time.set(str(cfg.get("send_time", "09:00")))
        self.var_include_chinese.set(bool(cfg.get("include_chinese", False)))
        self.var_provider.set(str(cfg.get("translation_provider", "local")))
        self.var_api_url.set(str(cfg.get("translation_url", "")))
        self.var_api_model.set(str(cfg.get("translation_model", "")))
        self.var_api_key.set(str(cfg.get("translation_api_key", "")))
        self._update_translation_ui()
        self.dirty = False

    def on_reset(self):
        """Discard edits and reload the last saved configuration."""
        if not self.dirty:
            self.log("当前没有未保存的修改。", "info")
            return
        if not messagebox.askyesno("重置设置", "放弃当前未保存的修改并恢复已保存设置？", parent=self.root):
            return
        self._load_cfg_to_ui()
        self.log("已恢复到上次保存的设置。", "ok")

    def _gather_cfg(self):
        cfg = core.read_config()
        cfg["smtp"]["host"] = self.var_smtp_host.get().strip()
        cfg["smtp"]["port"] = int(self.var_smtp_port.get().strip() or 465)
        cfg["smtp"]["user"] = self.var_sender.get().strip()
        cfg["smtp"]["auth_code"] = self.var_auth.get().strip()
        to = [x.strip() for x in self.var_to.get().split(",") if x.strip()]
        cfg["to"] = to
        cfg["language"] = self.var_lang.get().strip() or "all"
        cfg["top_n"] = int(self.var_topn.get().strip() or 25)
        cfg["send_time"] = self.var_time.get().strip() or "09:00"
        cfg["include_chinese"] = self.var_include_chinese.get()
        cfg["translation_provider"] = self.var_provider.get()
        cfg["translation_url"] = self.var_api_url.get().strip()
        cfg["translation_model"] = self.var_api_model.get().strip()
        cfg["translation_api_key"] = self.var_api_key.get().strip()
        return cfg

    def _mark_dirty(self):
        self.dirty = True

    # ---------- 异步任务 ----------
    def _run(self, fn, kind="done", *args):
        if self.busy:
            return
        self.busy = True
        self._set_busy(True)
        threading.Thread(target=self._worker, args=(fn, kind, args), daemon=True).start()

    def _worker(self, fn, kind, args):
        try:
            result = fn(*args)
            self.q.put((kind, result))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _render_preview_message(self, message):
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("end", message, "meta")
        self.preview_text.config(state="disabled")

    def _render_preview(self, payload):
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        repos = payload.get("repos", []) if isinstance(payload, dict) else []
        if not repos:
            self.preview_text.insert("end", "暂时没有可展示的项目。", "meta")
        else:
            title = f"{payload.get('date', '')}  ·  {payload.get('language', '')}  ·  Top {len(repos)}\n"
            self.preview_text.insert("end", title, "meta")
            self.preview_text.insert("end", f"数据来源：{payload.get('source', '')}\n", "meta")
            for index, repo in enumerate(repos, 1):
                name = str(repo.get("name", ""))
                stats = (f"Stars {repo.get('stars', '?')}  ·  今日新增 "
                         f"{('+' + str(repo.get('today'))) if repo.get('today') else '暂无数据'}  ·  "
                         f"{repo.get('lang') or '未标注'}")
                self.preview_text.insert("end", f"\n{index:02d}  {name}\n", "heading")
                self.preview_text.insert("end", stats + "\n", "meta")
                english = str(repo.get("desc_en") or "")
                chinese = str(repo.get("desc_zh") or "")
                if english:
                    self.preview_text.insert("end", "English: " + english + "\n", "description")
                if payload.get("include_chinese"):
                    self.preview_text.insert("end", "中文：" + (chinese or "暂时无法翻译") + "\n", "description")
                self.preview_text.insert("end", str(repo.get("url", "")) + "\n", "link")
        self.preview_text.config(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload[0], payload[1] if len(payload) > 1 else "info")
                elif kind == "preview":
                    self._render_preview(payload)
                    self._hide_progress()
                    self.home_status.config(text="预览已更新。")
                    self.busy = False
                    self._set_busy(False)
                elif kind == "done":
                    self._hide_progress()
                    self.busy = False
                    self._set_busy(False)
                    if payload:
                        self.log(str(payload), "ok")
                        self.home_status.config(text=str(payload))
                        if "邮件已发送" in str(payload):
                            self._show_success_toast("日报已发送", "邮件已成功送达发件服务")
                    self.root.after(250, lambda: self._refresh_task_status(schedule=False))
                elif kind == "task_status":
                    ok, nxt = payload
                    self.task_label.config(
                        text=f"定时任务：已开启（下次 {nxt or '待确认'}）" if ok else "定时任务：未开启")
                elif kind == "model_ready":
                    self._hide_progress()
                    self.busy = False
                    self._set_busy(False)
                    self.model_status.config(text="翻译模型：已准备好，可离线使用", fg=GREEN)
                    self.home_status.config(text="本地翻译模型已准备好。")
                elif kind == "error":
                    self._hide_progress()
                    self.busy = False
                    self._set_busy(False)
                    self.log("✗ " + str(payload), "err")
                    self.home_status.config(text="操作未完成，请查看设置页的运行记录。")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _set_busy(self, busy):
        self.root.config(cursor="watch" if busy else "")
        for b in self._action_buttons:
            b.set_state("disabled" if busy else "normal")

    def _show_success_toast(self, title, message):
        """Show a brief, non-modal success pill without taking keyboard focus."""
        if self._toast is not None:
            try:
                if self._toast_after:
                    self.root.after_cancel(self._toast_after)
                self._toast.destroy()
            except tk.TclError:
                pass
        toast = tk.Toplevel(self.root)
        self._toast = toast
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg="#20252B")
        toast_frame = tk.Frame(toast, bg="#20252B", padx=18, pady=12)
        toast_frame.pack(fill="both", expand=True)
        tk.Label(toast_frame, text="✓", bg="#20252B", fg="#75D6A3",
                 font=("Segoe UI", 18, "bold")).pack(side="left", padx=(0, 12))
        copy = tk.Frame(toast_frame, bg="#20252B")
        copy.pack(side="left", fill="both", expand=True)
        tk.Label(copy, text=title, bg="#20252B", fg="#FFFFFF",
                 font=FONT_B, anchor="w").pack(anchor="w")
        tk.Label(copy, text=message, bg="#20252B", fg="#C7CDD3",
                 font=FONT_SMALL, anchor="w").pack(anchor="w", pady=(2, 0))
        toast.update_idletasks()
        width, height = toast.winfo_reqwidth(), toast.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + 18
        toast.geometry(f"{width}x{height}+{max(8, x)}+{max(8, y)}")
        # No grab, focus_set, or modal wait: all app controls remain usable.
        self._toast_after = self.root.after(3600, self._dismiss_toast)

    def _dismiss_toast(self):
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        self._toast = None
        self._toast_after = None

    # ---------- 日志 ----------
    def log(self, msg, tag="info"):
        progress = re.search(r"正在下载(.+?)：(\d+)%（(.+?)）", msg)
        if progress:
            self._set_progress(f"正在下载 {progress.group(1)} · {progress.group(3)}",
                               int(progress.group(2)))
        elif "正在下载" in msg:
            self._set_progress(msg.split("正在下载", 1)[1], None)
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.config(state="disabled")
        self.log_text.see("end")

    # ---------- 操作 ----------
    def on_save(self):
        try:
            cfg = self._gather_cfg()
            core.validate_config(cfg)
            core.save_config(cfg)
            self.dirty = False
            self.log("✔ 配置已保存到 config.json", "ok")
            return True
        except ValueError as e:
            self.log("✗ " + str(e), "err")
        except Exception as e:
            self.log("✗ 保存失败：" + str(e), "err")
        return False

    def on_preview(self):
        if not self._email_configured():
            messagebox.showinfo("先完成邮箱设置", "请先在“设置”中填写发件邮箱、SMTP 授权码和收件邮箱，并保存设置。", parent=self.root)
            return
        try:
            cfg = self._gather_cfg()
        except Exception as e:
            self.log("✗ " + str(e), "err")
            return
        ready = core.translation_model_ready()
        if not cfg.get("include_chinese"):
            self.home_status.config(text="正在获取今日项目…")
        elif cfg.get("translation_provider") == "remote":
            self.home_status.config(text="正在获取项目并通过在线模型翻译简介…")
        else:
            self.home_status.config(text=("正在获取项目并翻译简介…" if ready else
                                          "首次翻译会下载模型，下载完成后可离线使用。"))
        self._set_progress("正在获取今日项目…" if ready else "正在准备本地翻译模型…", None)

        def _do():
            repos = core.fetch_trending(cfg["language"], cfg["top_n"])
            if cfg.get("include_chinese"):
                if cfg.get("translation_provider") == "remote":
                    for repo in repos:
                        repo["desc_en"] = str(repo.get("desc") or "")
                        repo["desc_zh"] = core._translate_remote(repo["desc_en"], cfg) if repo["desc_en"] else "暂无项目简介"
                else:
                    core.translate_descriptions(repos)
            language = cfg["language"] if cfg["language"] != "all" else "全部语言"
            return {"repos": repos, "date": datetime.date.today().isoformat(),
                    "language": language, "source": core.source_label(repos),
                    "include_chinese": bool(cfg.get("include_chinese"))}

        self._run(_do, kind="preview")

    def on_prepare_model(self):
        if core.translation_model_ready():
            self.log("翻译模型已下载，正在启动本地服务。", "info")
        else:
            self.log("首次下载约 1.31 GB；优先连接 ModelScope 国内源。", "head")
        self._set_progress("正在准备翻译模型…", None)
        self._run(core.prepare_translation_model, kind="model_ready")

    def on_send(self):
        try:
            cfg = self._gather_cfg()
            core.validate_config(cfg)
        except ValueError as e:
            self.log("✗ " + str(e), "err")
            return
        self.log("—— 开始抓取榜单并发送邮件……", "head")
        self._set_progress("正在准备邮件内容…", None)

        def _do():
            date_str, n, to = core.send_today_mail(cfg)
            return f"✔ {date_str} 共 {n} 个项目，邮件已发送到：{to}"

        self._run(_do)

    def _email_configured(self):
        return bool(self.var_sender.get().strip() and self.var_auth.get().strip()
                    and self.var_to.get().strip())

    def _set_progress(self, label, percent):
        self.progress_frame.pack(fill="x", pady=(0, 16), before=self.preview_text.master)
        self.progress_label.config(text=label)
        if percent is None:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="indeterminate")
            self.progress_bar.start(12)
            self.progress_percent.config(text="")
        else:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate", maximum=100, value=percent)
            self.progress_percent.config(text=f"{percent}%")

    def _hide_progress(self):
        self.progress_bar.stop()
        self.progress_frame.pack_forget()

    def on_enable_task(self):
        try:
            cfg = self._gather_cfg()
            t = cfg["send_time"]
        except Exception as e:
            self.log("✗ " + str(e), "err")
            return
        if not self.on_save():
            self.log("✗ 请先修正配置后再开启定时推送。", "err")
            return
        self.log(f"—— 正在注册每日定时任务（{t}）……", "head")

        def _do():
            core.register_task(t)
            ok, nxt = core.task_info()
            return f"✔ 定时推送已开启：每天 {t} 自动运行（下次运行 {nxt or '待确认'}）"

        self._run(_do)

    def on_disable_task(self):
        self.log("—— 正在取消定时推送……", "head")
        self._run(lambda: ("✔ 定时推送已取消", core.unregister_task())[0])

    def on_open_dir(self):
        core.open_base_dir()

    def on_open_log(self):
        core.os_startfile(core.LOG_PATH)

    def _refresh_task_status(self, schedule=True):
        def _do():
            ok, nxt = core.task_info()
            self.q.put(("task_status", (ok, nxt)))
        threading.Thread(target=_do, daemon=True).start()
        if schedule:
            self.root.after(30000, self._refresh_task_status)

    def _on_close(self):
        if self.tray and not self.tray.error:
            self.root.withdraw()
            self.log("StarTrace 已收至系统托盘。", "info")
        else:
            self._exit_app()

    def _exit_app(self):
        if self.dirty:
            answer = messagebox.askyesnocancel("保存配置", "配置有未保存的修改，是否保存后退出？", parent=self.root)
            if answer is None:
                return
            if answer and not self.on_save():
                return
        if self.tray:
            self.tray.stop()
        self.root.destroy()


def run():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    root.title(core.APP_NAME)
    root.geometry("960x840")
    root.minsize(680, 620)
    root.configure(bg=BG)
    try:
        resource_dir = Path(getattr(sys, "_MEIPASS", core.BASE_DIR))
        ico = resource_dir / "app.ico"
        if not ico.exists():
            ico = core.BASE_DIR / "app.ico"
        if ico.exists():
            root.iconbitmap(str(ico))
    except Exception:
        pass
    app = App(root)
    app.start_tray(ico if 'ico' in locals() else core.BASE_DIR / "app.ico")
    root.mainloop()


if __name__ == "__main__":
    run()
