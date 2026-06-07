# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import ImageGrab

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
VOCAB_PATH = DATA_DIR / "vocab.json"
CACHE_PATH = DATA_DIR / "ai_cache.json"
CONFIG_PATH = DATA_DIR / "config.json"
API_KEYS_PATH = DATA_DIR / "api_keys.json"
HISTORY_PATH = DATA_DIR / "history.json"

HOTKEY_ID = 702
WM_HOTKEY = 0x0312
MODIFIERS = {
    "ALT": 0x0001,
    "CONTROL": 0x0002,
    "CTRL": 0x0002,
    "SHIFT": 0x0004,
    "WIN": 0x0008,
}
MOD_NOREPEAT = 0x4000
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_ALT = 0x12
VK_SHIFT = 0x10
VK_WIN = 0x5B
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


DEFAULT_CONFIG = {
    "hotkey": {"modifiers": [], "key": "F8"},
    "restore_clipboard": True,
    "clipboard_plus_enabled": True,
    "ai_enabled": True,
    "openai_model": "gpt-4o-mini",
    "max_selection_chars": 120,
    "hotkey_action": "screen_ocr",
}

DEFAULT_API_KEYS = {
    "openai_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_model": "gpt-4o-mini",
    "openai_api_style": "responses"
}


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", POINT),
    ]


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        write_json(CONFIG_PATH, DEFAULT_CONFIG)
    if not CACHE_PATH.exists():
        write_json(CACHE_PATH, {})
    if not HISTORY_PATH.exists():
        write_json(HISTORY_PATH, {})
    if not API_KEYS_PATH.exists():
        write_json(API_KEYS_PATH, DEFAULT_API_KEYS)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_query(text: str, max_chars: int = 120) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n\"'`“”‘’.,;:!?()[]{}<>")
    return text[:max_chars].strip()


def hotkey_to_vk(key: str) -> int:
    key = key.upper()
    if len(key) == 1 and "A" <= key <= "Z":
        return ord(key)
    if len(key) == 1 and "0" <= key <= "9":
        return ord(key)
    aliases = {
        "SPACE": 0x20,
        "F1": 0x70,
        "F2": 0x71,
        "F3": 0x72,
        "F4": 0x73,
        "F5": 0x74,
        "F6": 0x75,
        "F7": 0x76,
        "F8": 0x77,
        "F9": 0x78,
        "F10": 0x79,
        "F11": 0x7A,
        "F12": 0x7B,
    }
    if key not in aliases:
        raise ValueError(f"Unsupported hotkey key: {key}")
    return aliases[key]


def format_hotkey(config: dict[str, Any]) -> str:
    hotkey = config.get("hotkey", {})
    modifiers = hotkey.get("modifiers", [])
    key = hotkey.get("key", "T")
    return "+".join([*modifiers, key])


def build_hotkey(config: dict[str, Any]) -> tuple[int, int]:
    hotkey = config.get("hotkey", DEFAULT_CONFIG["hotkey"])
    modifier_value = MOD_NOREPEAT
    for name in hotkey.get("modifiers", []):
        modifier_value |= MODIFIERS.get(str(name).upper(), 0)
    return modifier_value, hotkey_to_vk(str(hotkey.get("key", "T")))


def build_poll_keys(config: dict[str, Any]) -> list[int]:
    hotkey = config.get("hotkey", DEFAULT_CONFIG["hotkey"])
    keys: list[int] = []
    for name in hotkey.get("modifiers", []):
        modifier = str(name).upper()
        if modifier in ("CONTROL", "CTRL"):
            keys.append(VK_CONTROL)
        elif modifier == "ALT":
            keys.append(VK_ALT)
        elif modifier == "SHIFT":
            keys.append(VK_SHIFT)
        elif modifier == "WIN":
            keys.append(VK_WIN)
    keys.append(hotkey_to_vk(str(hotkey.get("key", "T"))))
    return keys


def is_key_down(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def get_cursor_position() -> tuple[int, int]:
    point = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def get_virtual_screen_bounds(root: tk.Tk) -> tuple[int, int, int, int]:
    if os.name != "nt":
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
    user32 = ctypes.windll.user32
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return x, y, width, height


def send_ctrl_c() -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(ord("C"), 0, 0, 0)
    user32.keybd_event(ord("C"), 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def get_openai_settings(config: dict[str, Any]) -> dict[str, str]:
    api_keys = read_json(API_KEYS_PATH, DEFAULT_API_KEYS)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip() or str(api_keys.get("openai_api_key", "")).strip()
    model = (
        os.environ.get("OPENAI_MODEL", "").strip()
        or str(api_keys.get("openai_model", "")).strip()
        or str(config.get("openai_model", "gpt-4o-mini"))
    )
    base_url = (
        os.environ.get("OPENAI_BASE_URL", "").strip()
        or str(api_keys.get("openai_base_url", "")).strip()
        or "https://api.openai.com/v1"
    )
    api_style = (
        os.environ.get("OPENAI_API_STYLE", "").strip()
        or str(api_keys.get("openai_api_style", "")).strip()
        or "responses"
    )
    return {
        "api_key": api_key,
        "model": model,
        "base_url": base_url.rstrip("/"),
        "api_style": api_style,
    }


def post_openai_json(settings: dict[str, str], path: str, body: dict[str, Any], label: str) -> dict[str, Any]:
    request = urllib.request.Request(
        settings["base_url"] + path,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{label}失败：HTTP {exc.code} {detail[:500]}") from exc


def extract_chat_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return ""


def call_openai(term: str, config: dict[str, Any]) -> dict[str, Any]:
    settings = get_openai_settings(config)
    if not settings["api_key"]:
        raise RuntimeError("还没有配置 OpenAI API key，所以不能用 AI 补充。请填写 data/api_keys.json。")

    prompt = f"""
你是一个给中文玩家使用的英语游戏词汇助手。请解释这个英文词或短语：{term}

只输出 JSON，不要 Markdown。字段必须是：
term: 原词
zh: 简明中文意思
phonetic: 标准 IPA 音标，不要中文谐音，不要近似读音
syllables: 用点号分开的英文音节，例如 stam·i·na
game_context: 它在游戏规则、UI、装备、战斗或任务文本里通常是什么意思
examples: 2 个短英文例句，每个例句后用中文解释
phrases: 3 个常见搭配
word_type: 词性或游戏 UI 类型，例如 noun / verb / status effect / UI label
category: 从 combat / status / equipment / quest / crafting / UI / multiplayer / general 中选择一个
tags: 2 到 5 个英文标签，例如 ["combat", "timing"]
common_confusions: 1 到 3 个容易混淆的词或用法
learning_note: 一个面向中文学习者的简短补充，强调语境、搭配或常见误读；不要写中文谐音
memory_hint: 一个帮助记忆的小提示
""".strip()
    if settings["api_style"] == "chat_completions":
        body = {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": "You return compact JSON for a Chinese gamer vocabulary helper."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        payload = post_openai_json(settings, "/chat/completions", body, "AI 请求")
        text = extract_chat_text(payload)
    else:
        body = {
            "model": settings["model"],
            "input": [
                {"role": "system", "content": "You return compact JSON for a Chinese gamer vocabulary helper."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        payload = post_openai_json(settings, "/responses", body, "AI 请求")
        text = extract_output_text(payload)

    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise RuntimeError("AI 返回内容不是可识别的 JSON。")
    data = json.loads(match.group(0))
    data["source"] = "ai"
    return data


def extract_output_text(payload: dict[str, Any]) -> str:
    text = payload.get("output_text", "")
    if text:
        return text
    parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if "text" in content:
                parts.append(content["text"])
    return "\n".join(parts)


def call_openai_vision_ocr(image_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    settings = get_openai_settings(config)
    if not settings["api_key"]:
        raise RuntimeError("框选识别需要 OpenAI API key，因为当前没有本地 OCR 引擎。请填写 data/api_keys.json。")

    import base64

    data_url = "data:image/png;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
    prompt = """
Extract the visible English word or short phrase from this selected screen region.
Return JSON only:
{
  "query": "the exact English word or short phrase to look up",
  "confidence": 0.0
}
If there are multiple words, choose the most prominent gameplay/UI term.
If no English text is visible, use an empty string for query.
""".strip()
    if settings["api_style"] == "chat_completions":
        body = {
            "model": settings["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0,
        }
        payload = post_openai_json(settings, "/chat/completions", body, "视觉识别")
        text = extract_chat_text(payload)
    else:
        body = {
            "model": settings["model"],
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
            "temperature": 0,
        }
        payload = post_openai_json(settings, "/responses", body, "视觉识别")
        text = extract_output_text(payload)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise RuntimeError("视觉识别返回内容不是可识别的 JSON。")
    return json.loads(match.group(0))


class WordPeekApp:
    def __init__(self, root: tk.Tk) -> None:
        ensure_data_files()
        self.root = root
        self.config = DEFAULT_CONFIG | read_json(CONFIG_PATH, {})
        self.vocab = read_json(VOCAB_PATH, {})
        self.cache = read_json(CACHE_PATH, {})
        self.history = read_json(HISTORY_PATH, {})
        self.stop_event = threading.Event()
        self.selection_overlay: tk.Toplevel | None = None
        self.plus_popup: tk.Toplevel | None = None
        self.last_clipboard_text = ""
        self.suppress_clipboard_until = 0.0
        self.current_term = ""
        self.current_entry: dict[str, Any] | None = None

        self.root.title("WordPeek 游戏词汇助手")
        self.root.geometry("560x520+900+180")
        self.root.minsize(460, 420)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.query_var = tk.StringVar()
        self.status_var = tk.StringVar(value=f"选中英文后按 {format_hotkey(self.config)}")
        self.source_var = tk.StringVar(value="")

        self.build_ui()
        self.start_hotkey_listener()
        self.start_clipboard_plus()

    def build_ui(self) -> None:
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Meta.TLabel", foreground="#5b6472")
        style.configure("Action.TButton", padding=(10, 6))

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x")

        entry = ttk.Entry(top, textvariable=self.query_var, font=("Segoe UI", 12))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.lookup_manual())

        ttk.Button(top, text="查一下", style="Action.TButton", command=self.lookup_manual).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="框选识别", style="Action.TButton", command=self.start_region_ocr).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="喇叭朗读", style="Action.TButton", command=self.speak_current).pack(side="left", padx=(8, 0))

        meta = ttk.Frame(outer)
        meta.pack(fill="x", pady=(10, 8))
        ttk.Label(meta, textvariable=self.status_var, style="Meta.TLabel").pack(side="left")
        ttk.Label(meta, textvariable=self.source_var, style="Meta.TLabel").pack(side="right")

        self.term_label = ttk.Label(outer, text="WordPeek", style="Title.TLabel")
        self.term_label.pack(anchor="w", pady=(4, 8))

        self.result_text = tk.Text(
            outer,
            wrap="word",
            height=16,
            font=("Microsoft YaHei UI", 11),
            relief="solid",
            borderwidth=1,
            padx=12,
            pady=10,
        )
        self.result_text.pack(fill="both", expand=True)
        self.result_text.configure(state="disabled")

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="保存到本地词库", command=self.save_current).pack(side="left")
        ttk.Button(bottom, text="常见词", command=self.show_common_words).pack(side="left", padx=(8, 0))
        ttk.Button(bottom, text="隐藏", command=self.root.withdraw).pack(side="right")

        self.root.bind("<Escape>", lambda _event: self.root.withdraw())
        self.show_text(
            "用法：\n"
            "1. 可复制文字：选中英文后按 Ctrl+C，鼠标旁会出现 +，点一下就查。\n"
            f"2. 不能复制的画面文字：按 {format_hotkey(self.config)}，拖框圈住英文。\n"
            "3. 本地词库没有时，会尝试用 AI 补充并缓存。\n\n"
            "你也可以直接在上面的输入框里手动输入。"
        )

    def start_hotkey_listener(self) -> None:
        if os.name != "nt":
            self.status_var.set("全局快捷键只在 Windows 上启用；当前可以手动查询。")
            return
        thread = threading.Thread(target=self.hotkey_poll_loop, daemon=True)
        thread.start()

    def hotkey_poll_loop(self) -> None:
        keys = build_poll_keys(self.config)
        was_pressed = False
        while not self.stop_event.is_set():
            pressed = all(is_key_down(vk) for vk in keys)
            if pressed and not was_pressed:
                action = self.config.get("hotkey_action", "screen_ocr")
                if action == "copy_selection":
                    self.root.after(0, self.lookup_selected_text)
                else:
                    self.root.after(0, self.start_region_ocr)
            was_pressed = pressed
            time.sleep(0.04)

    def clipboard_get(self) -> str:
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return ""

    def clipboard_set(self, text: str) -> None:
        self.suppress_clipboard_until = time.time() + 0.8
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def start_clipboard_plus(self) -> None:
        if not self.config.get("clipboard_plus_enabled", True):
            return
        self.last_clipboard_text = self.clipboard_get()
        self.root.after(700, self.poll_clipboard_for_plus)

    def poll_clipboard_for_plus(self) -> None:
        if self.stop_event.is_set():
            return
        try:
            text = self.clipboard_get()
            normalized = normalize_query(text, int(self.config.get("max_selection_chars", 120)))
            changed = text != self.last_clipboard_text
            self.last_clipboard_text = text
            if changed and time.time() >= self.suppress_clipboard_until and self.looks_like_lookup_text(normalized):
                cursor_x, cursor_y = get_cursor_position() if os.name == "nt" else (900, 180)
                self.show_plus_popup(normalized, cursor_x, cursor_y)
        finally:
            self.root.after(700, self.poll_clipboard_for_plus)

    def looks_like_lookup_text(self, text: str) -> bool:
        if not text or len(text) > int(self.config.get("max_selection_chars", 120)):
            return False
        if "\n" in text or "\r" in text:
            return False
        return bool(re.search(r"[A-Za-z]", text))

    def show_plus_popup(self, term: str, cursor_x: int, cursor_y: int) -> None:
        self.hide_plus_popup()
        popup = tk.Toplevel(self.root)
        self.plus_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#111827")

        button = tk.Button(
            popup,
            text="+",
            width=3,
            height=1,
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg="#16a34a",
            activeforeground="white",
            activebackground="#15803d",
            relief="flat",
            command=lambda: self.lookup_from_plus(term),
        )
        button.pack()
        popup.geometry(f"+{cursor_x + 14}+{cursor_y + 14}")
        popup.after(6000, self.hide_plus_popup)

    def hide_plus_popup(self) -> None:
        if self.plus_popup is not None:
            try:
                self.plus_popup.destroy()
            except tk.TclError:
                pass
            self.plus_popup = None

    def lookup_from_plus(self, term: str) -> None:
        self.hide_plus_popup()
        cursor_x, cursor_y = get_cursor_position() if os.name == "nt" else (900, 180)
        self.show_near_cursor(cursor_x, cursor_y)
        self.query_var.set(term)
        self.lookup(term)

    def capture_selection(self) -> str:
        previous = self.clipboard_get()
        marker = f"__WORDPEEK_{time.time_ns()}__"
        self.clipboard_set(marker)
        send_ctrl_c()
        selected = marker
        for _ in range(8):
            time.sleep(0.08)
            selected = self.clipboard_get()
            if selected != marker:
                break
        if self.config.get("restore_clipboard", True):
            self.clipboard_set(previous)
        if selected == marker:
            return ""
        return normalize_query(selected, int(self.config.get("max_selection_chars", 120)))

    def lookup_selected_text(self) -> None:
        cursor_x, cursor_y = get_cursor_position() if os.name == "nt" else (900, 180)
        term = self.capture_selection()
        self.show_near_cursor(cursor_x, cursor_y)
        if not term:
            self.status_var.set("没有读到选中文本。可以先选中英文，或在输入框里手动查。")
            return
        self.query_var.set(term)
        self.lookup(term)

    def start_region_ocr(self) -> None:
        if self.selection_overlay is not None:
            return
        self.root.withdraw()
        virtual_x, virtual_y, virtual_width, virtual_height = get_virtual_screen_bounds(self.root)
        cursor_x, cursor_y = get_cursor_position() if os.name == "nt" else (virtual_x + 24, virtual_y + 24)
        overlay = tk.Toplevel(self.root)
        self.selection_overlay = overlay
        overlay.overrideredirect(True)
        overlay.geometry(f"{virtual_width}x{virtual_height}+{virtual_x}+{virtual_y}")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.28)
        overlay.configure(bg="black")
        overlay.cursor = "crosshair"

        canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            max(cursor_x - virtual_x + 24, 24),
            max(cursor_y - virtual_y + 24, 24),
            anchor="nw",
            fill="white",
            text="拖框圈住要识别的英文区域，Esc 取消",
            font=("Microsoft YaHei UI", 18, "bold"),
        )

        state: dict[str, Any] = {"start": None, "rect": None}

        def cancel(_event: tk.Event | None = None) -> None:
            self.selection_overlay = None
            overlay.destroy()
            self.root.deiconify()
            self.root.lift()

        def on_down(event: tk.Event) -> None:
            canvas_x = event.x_root - virtual_x
            canvas_y = event.y_root - virtual_y
            state["start"] = (event.x_root, event.y_root, canvas_x, canvas_y)
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(canvas_x, canvas_y, canvas_x, canvas_y, outline="#5eead4", width=3)

        def on_drag(event: tk.Event) -> None:
            if not state["start"] or state["rect"] is None:
                return
            _sx_root, _sy_root, sx, sy = state["start"]
            canvas.coords(state["rect"], sx, sy, event.x_root - virtual_x, event.y_root - virtual_y)

        def on_up(event: tk.Event) -> None:
            if not state["start"]:
                cancel()
                return
            sx_root, sy_root, _sx, _sy = state["start"]
            x1, x2 = sorted((sx_root, event.x_root))
            y1, y2 = sorted((sy_root, event.y_root))
            self.selection_overlay = None
            overlay.destroy()
            if x2 - x1 < 8 or y2 - y1 < 8:
                self.show_near_cursor(event.x_root, event.y_root)
                self.status_var.set("框选区域太小，请重新框选英文。")
                return
            self.capture_and_ocr_region((x1, y1, x2, y2), event.x_root, event.y_root)

        overlay.bind("<Escape>", cancel)
        canvas.bind("<ButtonPress-1>", on_down)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_up)
        overlay.focus_force()

    def capture_and_ocr_region(self, bbox: tuple[int, int, int, int], cursor_x: int, cursor_y: int) -> None:
        self.show_near_cursor(cursor_x, cursor_y)
        self.status_var.set("正在识别框选区域...")
        self.source_var.set("来源：screen OCR")
        self.show_text("正在读取你框选的屏幕区域。\n\n如果这里卡住，通常是还没有配置 OPENAI_API_KEY。")
        capture_path = DATA_DIR / "last_capture.png"
        try:
            image = ImageGrab.grab(bbox=bbox, all_screens=True)
            image.save(capture_path)
        except Exception as exc:
            self.status_var.set("截图失败。")
            self.show_text(f"截图失败：{exc}")
            return
        worker = threading.Thread(target=self.ocr_worker, args=(capture_path,), daemon=True)
        worker.start()

    def ocr_worker(self, capture_path: Path) -> None:
        try:
            result = call_openai_vision_ocr(capture_path, self.config)
            query = normalize_query(str(result.get("query", "")), int(self.config.get("max_selection_chars", 120)))
            if not query:
                raise RuntimeError("框选区域里没有识别到英文。")
            self.root.after(0, lambda: self.finish_ocr_lookup(query, result))
        except Exception as exc:
            self.root.after(0, lambda: self.show_ocr_error(str(exc)))

    def finish_ocr_lookup(self, query: str, result: dict[str, Any]) -> None:
        confidence = result.get("confidence", "")
        self.query_var.set(query)
        if confidence != "":
            self.status_var.set(f"识别到：{query}，置信度：{confidence}")
        else:
            self.status_var.set(f"识别到：{query}")
        self.lookup(query)

    def show_ocr_error(self, error: str) -> None:
        self.source_var.set("来源：screen OCR")
        self.status_var.set("框选识别失败。")
        self.show_text(
            f"{error}\n\n"
            "现在这个版本要识别游戏画面/图片文字，需要 AI 视觉能力。\n"
            "请先填写 data/api_keys.json，然后重新打开 WordPeek。\n\n"
            "如果你只是在网页或文档里查可复制文字，也可以手动复制后在输入框里查。"
        )

    def show_near_cursor(self, cursor_x: int, cursor_y: int) -> None:
        self.root.deiconify()
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        if width < 460:
            width = 560
        if height < 420:
            height = 520
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = min(max(cursor_x + 18, 0), max(screen_width - width - 16, 0))
        y = min(max(cursor_y + 18, 0), max(screen_height - height - 48, 0))
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.lift()
        self.root.focus_force()

    def lookup_manual(self) -> None:
        term = normalize_query(self.query_var.get(), int(self.config.get("max_selection_chars", 120)))
        if term:
            self.lookup(term)

    def lookup(self, term: str) -> None:
        self.current_term = term
        key = term.lower()
        self.term_label.configure(text=term)
        self.source_var.set("")

        if key in self.vocab:
            self.show_entry(self.vocab[key] | {"term": term, "source": "local"})
            return
        if key in self.cache:
            self.show_entry(self.cache[key] | {"term": term, "source": "ai cache"})
            return

        self.current_entry = None
        self.status_var.set("本地词库没有，正在尝试 AI 补充...")
        self.show_text("正在补充这个词，稍等一下。")
        worker = threading.Thread(target=self.lookup_ai_worker, args=(term,), daemon=True)
        worker.start()

    def lookup_ai_worker(self, term: str) -> None:
        try:
            if not self.config.get("ai_enabled", True):
                raise RuntimeError("配置里关闭了 AI 补充。")
            entry = call_openai(term, self.config)
            self.cache[term.lower()] = entry
            write_json(CACHE_PATH, self.cache)
            self.root.after(0, lambda: self.show_entry(entry))
        except Exception as exc:
            self.root.after(0, lambda: self.show_ai_error(term, str(exc)))

    def show_ai_error(self, term: str, error: str) -> None:
        self.current_entry = None
        self.record_lookup(term, {"term": term, "source": "miss", "category": "general"})
        self.source_var.set("未补充")
        self.status_var.set("本地没有，AI 也暂时没补上。")
        self.show_text(
            f"词：{term}\n\n"
            "本地词库里还没有这个词。\n\n"
            f"{error}\n\n"
            "要开启 AI 补充：在系统环境变量里设置 OPENAI_API_KEY，"
            "然后重新打开这个工具。"
        )

    def show_entry(self, entry: dict[str, Any]) -> None:
        self.current_entry = entry
        self.current_term = entry.get("term") or self.current_term
        self.record_lookup(self.current_term, entry)
        self.term_label.configure(text=self.current_term)
        source = entry.get("source", "local")
        self.source_var.set(f"来源：{source}")
        self.status_var.set(f"已找到：{self.current_term}")

        lines = [
            f"中文：{entry.get('zh', '')}",
            f"音标：{entry.get('phonetic', entry.get('phonetic_hint', ''))}",
            f"音节：{entry.get('syllables', '')}",
            "",
            f"游戏语境：{entry.get('game_context', '')}",
        ]
        examples = entry.get("examples", [])
        if examples:
            lines.append("")
            lines.append("例句：")
            for item in examples:
                lines.append(f"- {item}")
        phrases = entry.get("phrases", entry.get("common_phrases", []))
        if phrases:
            lines.append("")
            lines.append("常见搭配：")
            for item in phrases:
                lines.append(f"- {item}")
        word_type = entry.get("word_type", "")
        if word_type:
            lines.append("")
            lines.append(f"类型：{word_type}")
        category = self.get_entry_category(entry)
        if category:
            lines.append("")
            lines.append(f"分类：{category}")
        tags = entry.get("tags", [])
        if tags:
            lines.append("")
            lines.append("标签：" + ", ".join(str(tag) for tag in tags))
        confusions = entry.get("common_confusions", [])
        if confusions:
            lines.append("")
            lines.append("易混点：")
            for item in confusions:
                lines.append(f"- {item}")
        learning_note = entry.get("learning_note", "")
        if learning_note:
            lines.append("")
            lines.append(f"学习备注：{learning_note}")
        hint = entry.get("memory_hint", "")
        if hint:
            lines.append("")
            lines.append(f"记忆提示：{hint}")
        self.show_text("\n".join(lines))

    def get_entry_category(self, entry: dict[str, Any]) -> str:
        category = str(entry.get("category", "")).strip()
        if category:
            return category
        text = " ".join(
            str(entry.get(field, ""))
            for field in ("term", "zh", "game_context", "word_type")
        ).lower()
        rules = [
            ("status", ["状态", "异常", "流血", "中毒", "debuff", "buff", "stun", "bleed"]),
            ("combat", ["攻击", "闪避", "招架", "弹反", "战斗", "伤害", "weapon", "damage", "parry", "dodge"]),
            ("equipment", ["装备", "武器", "护甲", "词条", "item", "gear", "weapon", "armor"]),
            ("quest", ["任务", "目标", "委托", "quest", "objective"]),
            ("crafting", ["制作", "合成", "材料", "craft", "material"]),
            ("UI", ["ui", "菜单", "界面", "设置", "marker", "label"]),
            ("multiplayer", ["队友", "团队", "仇恨", "多人", "team", "aggro", "multiplayer"]),
        ]
        for name, keywords in rules:
            if any(keyword in text for keyword in keywords):
                return name
        return "general"

    def record_lookup(self, term: str, entry: dict[str, Any]) -> None:
        key = normalize_query(term).lower()
        if not key:
            return
        item = self.history.get(key, {})
        count = int(item.get("count", 0)) + 1
        self.history[key] = {
            "term": entry.get("term") or term,
            "count": count,
            "last_seen": datetime.now().isoformat(timespec="seconds"),
            "source": entry.get("source", ""),
            "category": self.get_entry_category(entry),
        }
        write_json(HISTORY_PATH, self.history)

    def show_common_words(self) -> None:
        items = sorted(
            self.history.values(),
            key=lambda item: (int(item.get("count", 0)), str(item.get("last_seen", ""))),
            reverse=True,
        )
        if not items:
            self.show_text("还没有查询记录。查过的词会自动出现在这里。")
            return
        lines = ["常见词库："]
        for item in items[:30]:
            term = item.get("term", "")
            count = item.get("count", 0)
            category = item.get("category", "general")
            last_seen = item.get("last_seen", "")
            lines.append(f"- {term}  x{count}  [{category}]  {last_seen}")
        self.term_label.configure(text="常见词库")
        self.source_var.set("来源：history")
        self.status_var.set("按查询次数排序，自动记录。")
        self.show_text("\n".join(lines))

    def show_text(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def save_current(self) -> None:
        if not self.current_entry or not self.current_term:
            messagebox.showinfo("WordPeek", "当前没有可保存的词条。")
            return
        key = self.current_term.lower()
        entry = dict(self.current_entry)
        entry.pop("source", None)
        entry["term"] = self.current_term
        self.vocab[key] = entry
        write_json(VOCAB_PATH, self.vocab)
        self.status_var.set(f"已保存到本地词库：{self.current_term}")
        self.source_var.set("来源：local")

    def speak_current(self) -> None:
        text = normalize_query(self.query_var.get() or self.current_term, 80)
        if not text:
            return
        command = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = -1; "
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        try:
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", command],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if process.stdin:
                process.stdin.write(text)
                process.stdin.close()
        except Exception:
            self.status_var.set("朗读启动失败，但查询功能不受影响。")

    def on_close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def lookup_cli(term: str) -> int:
    ensure_data_files()
    vocab = read_json(VOCAB_PATH, {})
    cache = read_json(CACHE_PATH, {})
    key = normalize_query(term).lower()
    entry = vocab.get(key) or cache.get(key)
    if not entry:
        print(json.dumps({"term": term, "found": False}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(entry | {"found": True}, ensure_ascii=False, indent=2))
    return 0


def smoke_test() -> int:
    ensure_data_files()
    config = DEFAULT_CONFIG | read_json(CONFIG_PATH, {})
    build_hotkey(config)
    vocab = read_json(VOCAB_PATH, {})
    required = ["dodge", "parry", "stamina"]
    missing = [word for word in required if word not in vocab]
    if missing:
        print(f"Missing required starter words: {missing}")
        return 1
    print("WordPeek smoke test passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="WordPeek Windows vocabulary helper")
    parser.add_argument("--lookup", help="Look up a term from local vocab/cache and print JSON.")
    parser.add_argument("--smoke-test", action="store_true", help="Validate config and starter vocab.")
    args = parser.parse_args()

    if args.smoke_test:
        return smoke_test()
    if args.lookup:
        return lookup_cli(args.lookup)

    root = tk.Tk()
    WordPeekApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
