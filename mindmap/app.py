"""Tkinter-based desktop mind map editor."""
from __future__ import annotations

import colorsys
import copy
import json
import os
import subprocess
import sys
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog

try:  # pragma: no cover - fallback for running as a script
    from .model import MindMap, Node
except ImportError:  # pragma: no cover - executed when launched via ``python app.py``
    from model import MindMap, Node

NODE_RADIUS_X = 80
NODE_RADIUS_Y = 30
MAX_HISTORY = 50
AUTOSAVE_DELAY_MS = 1500


def _generate_palette() -> list[str]:
    colors: list[str] = []
    for row in range(16):
        brightness = 0.35 + (row / 15) * 0.6
        brightness = max(0.2, min(brightness, 1.0))
        for col in range(16):
            hue = col / 16
            r, g, b = colorsys.hsv_to_rgb(hue, 0.75, brightness)
            colors.append("#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
    return colors


COLOR_PALETTE = _generate_palette()

DEFAULT_SHORTCUTS: dict[str, str] = {
    "save": "<Control-s>",
    "open": "<Control-o>",
    "new": "<Control-n>",
    "quit": "<Control-q>",
    "undo": "<Control-z>",
    "redo": "<Control-y>",
    "auto_layout": "<Control-l>",
    "add_child": "<Control-Return>",
    "add_sibling": "<Shift-Return>",
    "rename": "<F2>",
    "delete": "<Delete>",
    "focus_search": "<Control-f>",
    "quick_add_child": "<Tab>",
    "quick_add_sibling": "<Return>",
    "copy": "<Control-c>",
    "paste": "<Control-v>",
}


SHORTCUT_LABELS = {
    "save": "保存",
    "open": "打开",
    "new": "新建",
    "quit": "退出",
    "undo": "撤销",
    "redo": "重做",
    "auto_layout": "自动排版",
    "add_child": "添加子节点",
    "add_sibling": "添加兄弟节点",
    "rename": "重命名",
    "delete": "删除",
    "focus_search": "搜索",
    "quick_add_child": "快速添加子节点",
    "quick_add_sibling": "快速添加兄弟节点",
    "copy": "复制",
    "paste": "粘贴",
}


GLOBAL_SHORTCUT_ACTIONS = {"quick_add_child", "quick_add_sibling"}


class MindMapApp:
    """A desktop mind map editor built with Tkinter."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._base_title = "MindMap GPT5"
        self.root.title(self._base_title)
        self.mind_map = MindMap()
        self.selected_node_id: int | None = None
        self.dragging_node_id: int | None = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self._history: list[dict] = []
        self._redo_stack: list[dict] = []
        self._pre_drag_snapshot: dict | None = None
        self._dragged = False
        self._updating_note = False
        self._drag_initial_positions: dict[int, tuple[float, float]] | None = None
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.current_file_path: Path | None = None
        self.autosave_path = Path.home() / ".mindmap_autosave.json"
        self._dirty = False
        self._autosave_after_id: str | None = None
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh(draw_selection=False))
        self.shortcuts_path = Path.home() / ".mindmap_shortcuts.json"
        self.shortcuts: dict[str, str] = DEFAULT_SHORTCUTS.copy()
        self._bound_shortcuts: dict[str, str] = {}
        self._menu_shortcut_entries: dict[str, tuple[tk.Menu, int]] = {}
        self._sidebar_shortcut_labels: dict[str, tk.Button] = {}
        self._shortcut_window: tk.Toplevel | None = None
        self._shortcut_instruction: tk.StringVar | None = None
        self._capturing_action: str | None = None
        self._shortcut_vars: dict[str, tk.StringVar] = {}
        self._clipboard_data: dict | None = None
        self._depth_limit: int | None = None
        self._visible_node_ids: set[int] = set()
        self._label_editor_entry: tk.Entry | None = None
        self._label_editor_window: int | None = None
        self._label_editor_var: tk.StringVar | None = None
        self._editing_node_id: int | None = None

        self._load_shortcuts()
        self._build_ui()
        self._ensure_root()
        self._maybe_restore_autosave()
        self._update_window_title()
        self._apply_shortcuts()

    def _build_ui(self) -> None:
        self.root.geometry("1200x750")

        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(
            label="新建",
            command=self.new_map,
            accelerator=self._format_shortcut_display("new"),
        )
        self._menu_shortcut_entries["new"] = (file_menu, file_menu.index("end"))
        file_menu.add_command(
            label="打开",
            command=self.load_from_file,
            accelerator=self._format_shortcut_display("open"),
        )
        self._menu_shortcut_entries["open"] = (file_menu, file_menu.index("end"))
        file_menu.add_command(
            label="保存",
            command=self.save_to_file,
            accelerator=self._format_shortcut_display("save"),
        )
        self._menu_shortcut_entries["save"] = (file_menu, file_menu.index("end"))
        export_menu = tk.Menu(file_menu, tearoff=False)
        export_menu.add_command(label="导出为 Markdown", command=self.export_markdown)
        export_menu.add_command(label="导出为文本", command=self.export_text)
        export_menu.add_command(label="导出为 JSON", command=self.export_json_copy)
        file_menu.add_cascade(label="导出", menu=export_menu)
        file_menu.add_separator()
        file_menu.add_command(
            label="退出",
            command=self.root.quit,
            accelerator=self._format_shortcut_display("quit"),
        )
        self._menu_shortcut_entries["quit"] = (file_menu, file_menu.index("end"))
        menubar.add_cascade(label="文件", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(
            label="撤销",
            command=self.undo,
            accelerator=self._format_shortcut_display("undo"),
        )
        self._menu_shortcut_entries["undo"] = (edit_menu, edit_menu.index("end"))
        edit_menu.add_command(
            label="重做",
            command=self.redo,
            accelerator=self._format_shortcut_display("redo"),
        )
        self._menu_shortcut_entries["redo"] = (edit_menu, edit_menu.index("end"))
        edit_menu.add_separator()
        edit_menu.add_command(
            label="添加子节点",
            command=self.add_child,
            accelerator=self._format_shortcut_display("add_child"),
        )
        self._menu_shortcut_entries["add_child"] = (edit_menu, edit_menu.index("end"))
        edit_menu.add_command(
            label="添加兄弟节点",
            command=self.add_sibling,
            accelerator=self._format_shortcut_display("add_sibling"),
        )
        self._menu_shortcut_entries["add_sibling"] = (edit_menu, edit_menu.index("end"))
        edit_menu.add_command(
            label="重命名",
            command=self.rename_selected,
            accelerator=self._format_shortcut_display("rename"),
        )
        self._menu_shortcut_entries["rename"] = (edit_menu, edit_menu.index("end"))
        edit_menu.add_command(
            label="删除",
            command=self.delete_selected,
            accelerator=self._format_shortcut_display("delete"),
        )
        self._menu_shortcut_entries["delete"] = (edit_menu, edit_menu.index("end"))
        edit_menu.add_separator()
        edit_menu.add_command(
            label="复制",
            command=self.copy_selected,
            accelerator=self._format_shortcut_display("copy"),
        )
        self._menu_shortcut_entries["copy"] = (edit_menu, edit_menu.index("end"))
        edit_menu.add_command(
            label="粘贴",
            command=self.paste_to_selected,
            accelerator=self._format_shortcut_display("paste"),
        )
        self._menu_shortcut_entries["paste"] = (edit_menu, edit_menu.index("end"))
        menubar.add_cascade(label="编辑", menu=edit_menu)

        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(
            label="自动排版",
            command=self.auto_layout,
            accelerator=self._format_shortcut_display("auto_layout"),
        )
        self._menu_shortcut_entries["auto_layout"] = (tools_menu, tools_menu.index("end"))
        tools_menu.add_separator()
        tools_menu.add_command(label="展开全部节点", command=lambda: self.set_depth_limit(None))
        tools_menu.add_command(label="展开到指定层级…", command=self.prompt_depth_limit)
        tools_menu.add_separator()
        tools_menu.add_command(label="更改背景颜色…", command=self.change_background)
        menubar.add_cascade(label="工具", menu=tools_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(label="快捷键设置…", command=self.open_shortcut_editor)
        menubar.add_cascade(label="设置", menu=settings_menu)

        self.root.config(menu=menubar)

        self.paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.paned, bg=self.mind_map.background, highlightthickness=0)
        self.paned.add(self.canvas, stretch="always")

        sidebar_wrapper = tk.Frame(self.paned, bg="#ffffff", relief=tk.GROOVE, borderwidth=1)
        self.paned.add(sidebar_wrapper, minsize=280)
        sidebar = tk.Frame(sidebar_wrapper, bg="#ffffff")
        sidebar.pack(fill=tk.BOTH, expand=True)
        self.sidebar = sidebar

        tk.Label(sidebar, text="工具", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(
            pady=(20, 10)
        )

        add_child_btn = tk.Button(sidebar, text=self._action_button_text("add_child"), command=self.add_child)
        add_child_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["add_child"] = add_child_btn

        add_sibling_btn = tk.Button(
            sidebar, text=self._action_button_text("add_sibling"), command=self.add_sibling
        )
        add_sibling_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["add_sibling"] = add_sibling_btn

        rename_btn = tk.Button(sidebar, text=self._action_button_text("rename"), command=self.rename_selected)
        rename_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["rename"] = rename_btn

        delete_btn = tk.Button(sidebar, text=self._action_button_text("delete"), command=self.delete_selected)
        delete_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["delete"] = delete_btn

        undo_btn = tk.Button(sidebar, text=self._action_button_text("undo"), command=self.undo)
        undo_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["undo"] = undo_btn

        redo_btn = tk.Button(sidebar, text=self._action_button_text("redo"), command=self.redo)
        redo_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["redo"] = redo_btn

        auto_btn = tk.Button(sidebar, text=self._action_button_text("auto_layout"), command=self.auto_layout)
        auto_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["auto_layout"] = auto_btn

        copy_btn = tk.Button(sidebar, text=self._action_button_text("copy"), command=self.copy_selected)
        copy_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["copy"] = copy_btn

        paste_btn = tk.Button(sidebar, text=self._action_button_text("paste"), command=self.paste_to_selected)
        paste_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["paste"] = paste_btn

        tk.Label(sidebar, text="搜索", font=("Helvetica", 14, "bold"), bg="#ffffff").pack(pady=(20, 5))
        search_entry = tk.Entry(sidebar, textvariable=self.search_var)
        search_entry.pack(fill=tk.X, padx=20)
        self._search_entry = search_entry

        focus_btn = tk.Button(
            sidebar,
            text=self._action_button_text("focus_search"),
            command=self.focus_search,
        )
        focus_btn.pack(fill=tk.X, padx=20, pady=5)
        self._sidebar_shortcut_labels["focus_search"] = focus_btn

        tk.Label(sidebar, text="文件", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(
            pady=(20, 10)
        )
        tk.Button(sidebar, text="保存", command=self.save_to_file).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="打开", command=self.load_from_file).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="新建", command=self.new_map).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="插入文件", command=self.attach_file).pack(fill=tk.X, padx=20, pady=5)

        tk.Label(sidebar, text="颜色", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(
            pady=(20, 10)
        )
        color_container = tk.Frame(sidebar, bg="#ffffff")
        color_container.pack(fill=tk.BOTH, expand=False, padx=20)
        color_canvas = tk.Canvas(color_container, height=240, bg="#ffffff", highlightthickness=0)
        color_scroll = tk.Scrollbar(color_container, orient=tk.VERTICAL, command=color_canvas.yview)
        color_canvas.configure(yscrollcommand=color_scroll.set)
        color_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        color_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        color_frame = tk.Frame(color_canvas, bg="#ffffff")
        color_canvas.create_window((0, 0), window=color_frame, anchor="nw")
        color_frame.bind(
            "<Configure>",
            lambda event: color_canvas.configure(scrollregion=color_canvas.bbox("all")),
        )
        for idx, color in enumerate(COLOR_PALETTE):
            btn = tk.Button(
                color_frame,
                bg=color,
                width=2,
                height=1,
                relief=tk.RIDGE,
                command=lambda c=color: self.set_color(c),
            )
            btn.grid(row=idx // 16, column=idx % 16, padx=2, pady=2)

        tk.Button(sidebar, text="更多颜色…", command=self.choose_custom_color).pack(
            fill=tk.X, padx=20, pady=(6, 0)
        )

        tk.Label(sidebar, text="备注", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(
            pady=(20, 5)
        )
        self.note_text = tk.Text(sidebar, height=10, wrap="word", relief=tk.SUNKEN, borderwidth=1)
        self.note_text.pack(fill=tk.BOTH, expand=True, padx=20)
        self.note_text.bind("<FocusOut>", self.on_note_focus_out)

        self.attachment_var = tk.StringVar(value="附件：无")
        self.attachment_label = tk.Label(
            sidebar,
            textvariable=self.attachment_var,
            bg="#ffffff",
            justify="left",
            wraplength=240,
        )
        self.attachment_label.pack(fill=tk.X, padx=20, pady=(10, 0))
        tk.Button(sidebar, text="打开附件", command=self.open_attachment).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="移除附件", command=self.remove_attachment).pack(fill=tk.X, padx=20, pady=5)

        tk.Label(sidebar, text="外观", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(pady=(20, 10))
        tk.Button(sidebar, text="更改背景颜色…", command=self.change_background).pack(
            fill=tk.X, padx=20, pady=5
        )
        tk.Button(sidebar, text="展开到指定层级…", command=self.prompt_depth_limit).pack(
            fill=tk.X, padx=20, pady=5
        )
        tk.Button(sidebar, text="展开全部节点", command=lambda: self.set_depth_limit(None)).pack(
            fill=tk.X, padx=20, pady=5
        )

        self.context_menu = tk.Menu(self.root, tearoff=False)
        self.context_menu.add_command(label="添加子节点", command=self.add_child)
        self.context_menu.add_command(label="添加兄弟节点", command=self.add_sibling)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="重命名", command=self.rename_selected)
        self.context_menu.add_command(label="删除", command=self.delete_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制", command=self.copy_selected)
        self.context_menu.add_command(label="粘贴", command=self.paste_to_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="插入文件", command=self.attach_file)
        self.context_menu.add_command(label="打开附件", command=self.open_attachment)
        self.context_menu.add_command(label="移除附件", command=self.remove_attachment)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="自动排版", command=self.auto_layout)

        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Double-1>", self.on_canvas_double_click)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<Control-MouseWheel>", self.on_zoom)
        self.canvas.bind("<Control-Button-4>", lambda event: self.on_zoom(event, delta=120))
        self.canvas.bind("<Control-Button-5>", lambda event: self.on_zoom(event, delta=-120))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _format_sequence_for_display(self, sequence: str | None) -> str:
        if not sequence:
            return ""
        cleaned = sequence.strip("<>")
        if not cleaned:
            return ""
        parts = cleaned.split("-")
        display_parts: list[str] = []
        for part in parts:
            lower = part.lower()
            if lower in {"control", "ctrl"}:
                display_parts.append("Ctrl")
            elif lower == "shift":
                display_parts.append("Shift")
            elif lower in {"alt", "option"}:
                display_parts.append("Alt")
            elif lower == "return":
                display_parts.append("Enter")
            elif lower == "space":
                display_parts.append("Space")
            elif len(part) == 1:
                display_parts.append(part.upper())
            else:
                display_parts.append(part.capitalize())
        return "+".join(display_parts)

    def _format_shortcut_display(self, action: str) -> str:
        return self._format_sequence_for_display(self.shortcuts.get(action))

    def _action_button_text(self, action: str) -> str:
        base = SHORTCUT_LABELS.get(action, action)
        shortcut = self._format_shortcut_display(action)
        return f"{base} ({shortcut})" if shortcut else base

    def _update_shortcut_labels(self) -> None:
        for action, (menu, index) in self._menu_shortcut_entries.items():
            menu.entryconfig(index, accelerator=self._format_shortcut_display(action))
        for action, button in self._sidebar_shortcut_labels.items():
            button.configure(text=self._action_button_text(action))

    def _load_shortcuts(self) -> None:
        if not self.shortcuts_path.exists():
            return
        try:
            data = json.loads(self.shortcuts_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for action, sequence in data.items():
            if action in self.shortcuts and isinstance(sequence, str):
                self.shortcuts[action] = sequence

    def _save_shortcuts(self) -> None:
        try:
            self.shortcuts_path.write_text(
                json.dumps(self.shortcuts, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _invoke_quit(self, _event: tk.Event | None = None) -> None:
        self.root.quit()

    def _get_shortcut_handler(self, action: str):
        handlers: dict[str, callable] = {
            "save": self.save_to_file,
            "open": self.load_from_file,
            "new": self.new_map,
            "quit": self._invoke_quit,
            "undo": self.undo,
            "redo": self.redo,
            "auto_layout": self.auto_layout,
            "add_child": self.add_child,
            "add_sibling": self.add_sibling,
            "rename": self.rename_selected,
            "delete": self.delete_selected,
            "focus_search": self.focus_search,
            "quick_add_child": self.quick_add_child,
            "quick_add_sibling": self.quick_add_sibling,
            "copy": self.copy_selected,
            "paste": self.paste_to_selected,
        }
        return handlers.get(action)

    def _apply_shortcuts(self) -> None:
        for action, sequence in list(self._bound_shortcuts.items()):
            if not sequence:
                continue
            if action in GLOBAL_SHORTCUT_ACTIONS:
                self.root.unbind_all(sequence)
            else:
                self.root.unbind(sequence)
        self._bound_shortcuts.clear()

        for action, sequence in self.shortcuts.items():
            if not sequence:
                continue
            handler = self._get_shortcut_handler(action)
            if handler is None:
                continue
            if action in GLOBAL_SHORTCUT_ACTIONS:
                self.root.bind_all(sequence, handler, add="+")
            else:
                self.root.bind(sequence, handler, add="+")
            self._bound_shortcuts[action] = sequence

        self._update_shortcut_labels()
        self._save_shortcuts()

    def open_shortcut_editor(self) -> None:
        if self._shortcut_window is not None and self._shortcut_window.winfo_exists():
            self._shortcut_window.lift()
            self._shortcut_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        window.title("快捷键设置")
        window.geometry("420x500")
        window.transient(self.root)
        window.grab_set()
        self._shortcut_window = window
        self._shortcut_instruction = tk.StringVar(
            value="点击“修改”后，按下新的快捷键。按 Esc 取消。"
        )
        instruction = tk.Label(window, textvariable=self._shortcut_instruction, anchor="w")
        instruction.pack(fill=tk.X, padx=12, pady=(12, 0))

        container = tk.Frame(window)
        container.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self._shortcut_vars.clear()
        for action, label in SHORTCUT_LABELS.items():
            if action not in self.shortcuts:
                continue
            row = tk.Frame(container)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label, width=16, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=self._format_shortcut_display(action))
            entry = tk.Entry(row, textvariable=var, state="readonly", justify="center", width=18)
            entry.pack(side=tk.LEFT, padx=6)
            self._shortcut_vars[action] = var
            tk.Button(row, text="修改", command=lambda a=action: self._start_capture_shortcut(a)).pack(
                side=tk.LEFT, padx=4
            )
            tk.Button(row, text="清除", command=lambda a=action: self._clear_shortcut(a)).pack(side=tk.LEFT)

        tk.Button(window, text="恢复默认", command=self._reset_shortcuts).pack(pady=(0, 12))
        window.protocol("WM_DELETE_WINDOW", self._on_shortcut_editor_close)
        window.bind("<Destroy>", self._shortcut_editor_closed)

    def _on_shortcut_editor_close(self) -> None:
        if self._shortcut_window is not None:
            self._shortcut_window.destroy()

    def _start_capture_shortcut(self, action: str) -> None:
        if self._shortcut_window is None or not self._shortcut_window.winfo_exists():
            return
        self._capturing_action = action
        if self._shortcut_instruction is not None:
            self._shortcut_instruction.set(
                f"为“{SHORTCUT_LABELS.get(action, action)}”按下新的快捷键，Esc 取消。"
            )
        self._shortcut_window.bind("<Key>", self._on_shortcut_key)
        self._shortcut_window.focus_force()

    def _on_shortcut_key(self, event: tk.Event) -> str:
        if self._capturing_action is None:
            return "break"
        if event.keysym == "Escape":
            self._capturing_action = None
            if self._shortcut_instruction is not None:
                self._shortcut_instruction.set("已取消快捷键修改。")
            if self._shortcut_window is not None:
                self._shortcut_window.unbind("<Key>")
            return "break"
        sequence = self._event_to_sequence(event)
        if sequence is None:
            return "break"
        action = self._capturing_action
        self.shortcuts[action] = sequence
        if action in self._shortcut_vars:
            self._shortcut_vars[action].set(self._format_sequence_for_display(sequence))
        self._capturing_action = None
        if self._shortcut_instruction is not None:
            self._shortcut_instruction.set("快捷键已更新。")
        if self._shortcut_window is not None:
            self._shortcut_window.unbind("<Key>")
        self._apply_shortcuts()
        return "break"

    def _event_to_sequence(self, event: tk.Event) -> str | None:
        key = event.keysym
        if key in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}:
            return None
        modifiers: list[str] = []
        if event.state & 0x0004:
            modifiers.append("Control")
        if event.state & 0x0001:
            modifiers.append("Shift")
        if event.state & 0x0008:
            modifiers.append("Alt")
        key_name = key
        if len(key_name) == 1:
            key_name = key_name.lower()
        return "<" + "-".join(modifiers + [key_name]) + ">"

    def _clear_shortcut(self, action: str) -> None:
        if action in self.shortcuts:
            self.shortcuts[action] = ""
        if action in self._shortcut_vars:
            self._shortcut_vars[action].set("")
        self._apply_shortcuts()

    def _reset_shortcuts(self) -> None:
        self.shortcuts = DEFAULT_SHORTCUTS.copy()
        for action, var in self._shortcut_vars.items():
            var.set(self._format_shortcut_display(action))
        self._apply_shortcuts()

    def _shortcut_editor_closed(self, event: tk.Event | None = None) -> None:
        if self._shortcut_window is None:
            return
        if event is not None and event.widget is not self._shortcut_window:
            return
        self._shortcut_window.unbind("<Key>")
        self._shortcut_window = None
        self._capturing_action = None
        self._shortcut_instruction = None
        self._shortcut_vars.clear()

    def _ensure_root(self) -> None:
        if self.mind_map.root_id is None:
            node = self.mind_map.create_root()
            self.selected_node_id = node.id
            self._history.clear()
            self._redo_stack.clear()
            self._history.append(copy.deepcopy(self.mind_map.to_dict()))
            self._depth_limit = None
            self.refresh()
            self.start_inline_edit(node.id, select_all=True)
        else:
            self._depth_limit = None
            self.refresh()

    def _maybe_restore_autosave(self) -> None:
        if not self.autosave_path.exists():
            return
        try:
            if messagebox.askyesno("恢复", "检测到自动保存文件，是否恢复上次编辑内容？"):
                data = json.loads(self.autosave_path.read_text(encoding="utf-8"))
                self.mind_map = MindMap.from_dict(data)
                self.selected_node_id = self.mind_map.root_id
                self._history = [copy.deepcopy(self.mind_map.to_dict())]
                self._redo_stack.clear()
                self._dirty = False
                self.current_file_path = None
                self.refresh()
        except Exception as exc:  # pragma: no cover - Tkinter message box
            messagebox.showwarning("警告", f"自动保存文件损坏：{exc}")

    def _update_window_title(self) -> None:
        parts = [self._base_title]
        if self.current_file_path:
            parts.append(f"- {self.current_file_path.name}")
        if self._dirty:
            parts.append("*")
        self.root.title(" ".join(parts))

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_window_title()
        self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if self._autosave_after_id is not None:
            self.root.after_cancel(self._autosave_after_id)
        self._autosave_after_id = self.root.after(AUTOSAVE_DELAY_MS, self._perform_autosave)

    def _cancel_autosave(self) -> None:
        if self._autosave_after_id is not None:
            self.root.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None

    def _perform_autosave(self) -> None:
        self._autosave_after_id = None
        if not self._dirty:
            return
        data = self.mind_map.to_dict()
        target = self.current_file_path or self.autosave_path
        try:
            Path(target).write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._dirty = False
            self._update_window_title()
        except Exception as exc:  # pragma: no cover - Tkinter message box
            messagebox.showwarning("警告", f"自动保存失败：{exc}")

    def on_close(self) -> None:
        try:
            self._perform_autosave()
        finally:
            self.root.destroy()

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.offset_x, y * self.scale + self.offset_y

    def to_world(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def _save_state(self) -> None:
        self._history.append(copy.deepcopy(self.mind_map.to_dict()))
        if len(self._history) > MAX_HISTORY:
            self._history.pop(0)
        self._redo_stack.clear()

    def add_child(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个父节点")
            return
        self._save_state()
        node = self.mind_map.add_child(self.selected_node_id, "")
        self._ensure_depth_visible(node.id)
        self.selected_node_id = node.id
        self.refresh()
        self._mark_dirty()
        self.start_inline_edit(node.id, select_all=True)

    def add_sibling(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个节点")
            return
        try:
            self._save_state()
            node = self.mind_map.add_sibling(self.selected_node_id, "")
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        self._ensure_depth_visible(node.id)
        self.selected_node_id = node.id
        self.refresh()
        self._mark_dirty()
        self.start_inline_edit(node.id, select_all=True)

    def rename_selected(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个节点")
            return
        self.start_inline_edit(self.selected_node_id, select_all=True)

    def start_inline_edit(self, node_id: int, select_all: bool = False) -> None:
        try:
            node = self.mind_map.get_node(node_id)
        except KeyError:
            return
        if self._visible_node_ids and node_id not in self._visible_node_ids:
            return
        self._clear_inline_editor()
        self._editing_node_id = node_id
        self._label_editor_var = tk.StringVar(value=node.label)
        font_size = max(int(12 * self.scale), 8)
        entry = tk.Entry(
            self.canvas,
            textvariable=self._label_editor_var,
            font=("Helvetica", font_size, "bold"),
            justify="center",
        )
        center_x, center_y = self.to_screen(node.x, node.y)
        width = max(int(NODE_RADIUS_X * 2 * self.scale), 120)
        height = max(int(NODE_RADIUS_Y * 1.8 * self.scale), 28)
        window = self.canvas.create_window(
            center_x,
            center_y,
            window=entry,
            width=width,
            height=height,
        )
        self._label_editor_entry = entry
        self._label_editor_window = window
        entry.focus_set()
        if select_all:
            entry.select_range(0, tk.END)
        entry.bind("<Return>", self._commit_inline_edit)
        entry.bind("<KP_Enter>", self._commit_inline_edit)
        entry.bind("<Escape>", self._cancel_inline_edit)
        entry.bind("<FocusOut>", self._commit_inline_edit)

    def _commit_inline_edit(self, _event: tk.Event | None = None) -> str:
        if self._editing_node_id is None or self._label_editor_var is None:
            self._clear_inline_editor()
            return "break"
        node = self.mind_map.get_node(self._editing_node_id)
        new_label = self._label_editor_var.get()
        self._clear_inline_editor()
        if new_label != node.label:
            self._save_state()
            self.mind_map.rename_node(node.id, new_label)
            self.refresh()
            self._mark_dirty()
        return "break"

    def _cancel_inline_edit(self, _event: tk.Event | None = None) -> str:
        self._clear_inline_editor()
        return "break"

    def _clear_inline_editor(self) -> None:
        if self._label_editor_window is not None:
            try:
                self.canvas.delete(self._label_editor_window)
            except Exception:
                pass
            self._label_editor_window = None
        if self._label_editor_entry is not None and self._label_editor_entry.winfo_exists():
            self._label_editor_entry.destroy()
        self._label_editor_entry = None
        self._label_editor_var = None
        self._editing_node_id = None

    def delete_selected(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            return
        if self.selected_node_id == self.mind_map.root_id:
            messagebox.showwarning("警告", "不能删除根节点")
            return
        if messagebox.askyesno("确认", "确定要删除选中的节点及其子节点吗？"):
            self._save_state()
            self.mind_map.delete_node(self.selected_node_id)
            self.selected_node_id = self.mind_map.root_id
            self.refresh()
            self._mark_dirty()

    def save_to_file(self, _event: tk.Event | None = None) -> None:
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            title="保存思维导图",
        )
        if not file_path:
            return
        data = self.mind_map.to_dict()
        Path(file_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.current_file_path = Path(file_path)
        self._dirty = False
        self._cancel_autosave()
        self._update_window_title()
        messagebox.showinfo("保存成功", "思维导图已保存")

    def load_from_file(self, _event: tk.Event | None = None) -> None:
        file_path = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            title="打开思维导图",
        )
        if not file_path:
            return
        try:
            data = json.loads(Path(file_path).read_text(encoding="utf-8"))
            self.mind_map = MindMap.from_dict(data)
            if self.mind_map.root_id is None and self.mind_map.nodes():
                self.mind_map.root_id = min(node.id for node in self.mind_map.nodes())
            self.selected_node_id = self.mind_map.root_id
            self._history = [copy.deepcopy(self.mind_map.to_dict())]
            self._redo_stack.clear()
            self.current_file_path = Path(file_path)
            self._dirty = False
            self._cancel_autosave()
            self._update_window_title()
            self._depth_limit = None
            self.refresh()
        except Exception as exc:  # pragma: no cover - Tkinter message box
            messagebox.showerror("错误", f"加载文件失败: {exc}")

    def export_markdown(self) -> None:
        file_path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("所有文件", "*.*")],
            title="导出为 Markdown",
        )
        if not file_path:
            return

        def walk(node_id: int, depth: int, lines: list[str]) -> None:
            node = self.mind_map.get_node(node_id)
            prefix = "    " * depth + "- "
            attachment = f" (附件: {node.attachment})" if node.attachment else ""
            note_block = f" — {node.note.strip()}" if node.note.strip() else ""
            lines.append(f"{prefix}{node.label}{attachment}{note_block}")
            for child_id in node.children:
                walk(child_id, depth + 1, lines)

        if self.mind_map.root_id is None:
            messagebox.showinfo("提示", "暂无内容可导出")
            return

        lines: list[str] = ["# 思维导图导出", ""]
        walk(self.mind_map.root_id, 0, lines)
        Path(file_path).write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("完成", "已导出为 Markdown")

    def export_text(self) -> None:
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            title="导出为文本",
        )
        if not file_path:
            return

        def walk(node_id: int, depth: int, lines: list[str]) -> None:
            node = self.mind_map.get_node(node_id)
            prefix = "    " * depth
            attachment = f" [附件: {node.attachment}]" if node.attachment else ""
            note_block = f" :: {node.note.strip()}" if node.note.strip() else ""
            lines.append(f"{prefix}{node.label}{attachment}{note_block}")
            for child_id in node.children:
                walk(child_id, depth + 1, lines)

        if self.mind_map.root_id is None:
            messagebox.showinfo("提示", "暂无内容可导出")
            return

        lines: list[str] = []
        walk(self.mind_map.root_id, 0, lines)
        Path(file_path).write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("完成", "已导出为文本文件")

    def export_json_copy(self) -> None:
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            title="另存 JSON 副本",
        )
        if not file_path:
            return
        data = self.mind_map.to_dict()
        Path(file_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("完成", "JSON 副本已导出")

    def attach_file(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个节点后再插入附件")
            return
        file_path = filedialog.askopenfilename(title="选择要插入的文件")
        if not file_path:
            return
        self._save_state()
        node = self.mind_map.get_node(self.selected_node_id)
        if not node.label:
            node.label = Path(file_path).name
        self.mind_map.update_attachment(node.id, file_path)
        self.refresh()
        self._mark_dirty()

    def open_attachment(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            return
        node = self.mind_map.get_node(self.selected_node_id)
        if not node.attachment:
            messagebox.showinfo("提示", "该节点没有附件")
            return
        path = Path(node.attachment)
        if not path.exists():
            messagebox.showwarning("警告", "附件文件不存在")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.call(["open", str(path)])
            else:
                subprocess.call(["xdg-open", str(path)])
        except Exception as exc:  # pragma: no cover - Tkinter message box
            messagebox.showerror("错误", f"无法打开附件: {exc}")

    def remove_attachment(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            return
        node = self.mind_map.get_node(self.selected_node_id)
        if not node.attachment:
            return
        self._save_state()
        self.mind_map.update_attachment(node.id, None)
        self.refresh()
        self._mark_dirty()

    def copy_selected(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择要复制的节点")
            return
        subtree = self.mind_map.serialize_subtree(self.selected_node_id)
        self._clipboard_data = copy.deepcopy(subtree)

    def paste_to_selected(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None or not self._clipboard_data:
            messagebox.showinfo("提示", "没有可粘贴的内容或未选择目标节点")
            return
        subtree = copy.deepcopy(self._clipboard_data)
        parent = self.mind_map.get_node(self.selected_node_id)
        offset_x = parent.x + 200 - subtree.get("x", parent.x)
        offset_y = parent.y - subtree.get("y", parent.y)
        self._save_state()
        new_root = self.mind_map.insert_subtree(self.selected_node_id, subtree, offset_x, offset_y)
        self._ensure_depth_visible(new_root.id)
        self.selected_node_id = new_root.id
        self.refresh()
        self._mark_dirty()
        self.start_inline_edit(new_root.id, select_all=True)

    def quick_add_child(self, event: tk.Event | None = None) -> str | None:
        if event is not None and (event.state & (0x1 | 0x4 | 0x8)):
            return None
        focus_widget = self.root.focus_get()
        if focus_widget not in {None, self.canvas}:
            return None
        if self.selected_node_id is None:
            return "break"
        self.add_child()
        return "break"

    def quick_add_sibling(self, event: tk.Event | None = None) -> str | None:
        if event is not None and (event.state & (0x1 | 0x4 | 0x8)):
            return None
        focus_widget = self.root.focus_get()
        if focus_widget not in {None, self.canvas}:
            return None
        if self.selected_node_id is None:
            return "break"
        self.add_sibling()
        return "break"

    def on_zoom(self, event: tk.Event, delta: int | None = None) -> None:
        if delta is None:
            delta = event.delta
        if delta == 0:
            return
        factor = 1.1 if delta > 0 else 1 / 1.1
        new_scale = min(max(self.scale * factor, 0.2), 4.0)
        factor = new_scale / self.scale
        world_x, world_y = self.to_world(event.x, event.y)
        self.scale = new_scale
        self.offset_x = event.x - world_x * self.scale
        self.offset_y = event.y - world_y * self.scale
        self.refresh(draw_selection=False)
    def on_canvas_click(self, event: tk.Event[tk.Canvas]) -> None:
        world_x, world_y = self.to_world(event.x, event.y)
        node_id = self._find_node_at(world_x, world_y)
        self._dragged = False
        if node_id is not None:
            self.selected_node_id = node_id
            node = self.mind_map.get_node(node_id)
            self.dragging_node_id = node_id
            self.drag_offset_x = node.x - world_x
            self.drag_offset_y = node.y - world_y
            self._pre_drag_snapshot = copy.deepcopy(self.mind_map.to_dict())
            subtree_ids = self.mind_map.subtree_node_ids(node_id)
            self._drag_initial_positions = {
                nid: (self.mind_map.get_node(nid).x, self.mind_map.get_node(nid).y)
                for nid in subtree_ids
            }
        else:
            self.selected_node_id = None
            self.dragging_node_id = None
            self._pre_drag_snapshot = None
            self._drag_initial_positions = None
        self.canvas.focus_set()
        self.refresh()

    def on_canvas_drag(self, event: tk.Event[tk.Canvas]) -> None:
        if self.dragging_node_id is None:
            return
        world_x, world_y = self.to_world(event.x, event.y)
        new_x = world_x + self.drag_offset_x
        new_y = world_y + self.drag_offset_y
        if self._drag_initial_positions is None:
            self.mind_map.move_node(self.dragging_node_id, new_x, new_y)
        else:
            base_x, base_y = self._drag_initial_positions[self.dragging_node_id]
            delta_x = new_x - base_x
            delta_y = new_y - base_y
            for nid, (orig_x, orig_y) in self._drag_initial_positions.items():
                self.mind_map.move_node(nid, orig_x + delta_x, orig_y + delta_y)
        self._dragged = True
        self.refresh(draw_selection=False)

    def on_canvas_double_click(self, event: tk.Event[tk.Canvas]) -> None:
        world_x, world_y = self.to_world(event.x, event.y)
        node_id = self._find_node_at(world_x, world_y)
        if node_id is None:
            return
        self.selected_node_id = node_id
        self.refresh()
        self.start_inline_edit(node_id, select_all=True)

    def on_canvas_release(self, _event: tk.Event[tk.Canvas]) -> None:
        if self.dragging_node_id is not None and self._dragged and self._pre_drag_snapshot is not None:
            self._history.append(self._pre_drag_snapshot)
            if len(self._history) > MAX_HISTORY:
                self._history.pop(0)
            self._redo_stack.clear()
            self._pre_drag_snapshot = None
            self._mark_dirty()
        self.dragging_node_id = None
        self._drag_initial_positions = None

    def show_context_menu(self, event: tk.Event[tk.Canvas]) -> None:
        world_x, world_y = self.to_world(event.x, event.y)
        node_id = self._find_node_at(world_x, world_y)
        if node_id is not None:
            self.selected_node_id = node_id
            self.refresh(draw_selection=False)
        if self.selected_node_id is not None:
            node = self.mind_map.get_node(self.selected_node_id)
            state = tk.NORMAL if node.attachment else tk.DISABLED
            self.context_menu.entryconfig("打开附件", state=state)
            self.context_menu.entryconfig("移除附件", state=state)
            self.context_menu.entryconfig("复制", state=tk.NORMAL)
            paste_state = tk.NORMAL if self._clipboard_data is not None else tk.DISABLED
            self.context_menu.entryconfig("粘贴", state=paste_state)
            self.context_menu.entryconfig("重命名", state=tk.NORMAL)
            self.context_menu.entryconfig("删除", state=tk.NORMAL)
        else:
            self.context_menu.entryconfig("打开附件", state=tk.DISABLED)
            self.context_menu.entryconfig("移除附件", state=tk.DISABLED)
            self.context_menu.entryconfig("复制", state=tk.DISABLED)
            self.context_menu.entryconfig("粘贴", state=tk.DISABLED if self._clipboard_data is None else tk.NORMAL)
            self.context_menu.entryconfig("重命名", state=tk.DISABLED)
            self.context_menu.entryconfig("删除", state=tk.DISABLED)
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def focus_search(self, _event: tk.Event | None = None) -> None:
        self._search_entry.focus_set()

    def set_color(self, color: str) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个节点")
            return
        self._save_state()
        self.mind_map.update_color(self.selected_node_id, color)
        self.refresh()
        self._mark_dirty()

    def on_note_focus_out(self, _event: tk.Event | None = None) -> None:
        if self._updating_note or self.selected_node_id is None:
            return
        note = self.note_text.get("1.0", tk.END).rstrip()
        node = self.mind_map.get_node(self.selected_node_id)
        if note == node.note:
            return
        self._save_state()
        self.mind_map.update_note(self.selected_node_id, note)
        self.refresh(draw_selection=False)
        self._mark_dirty()

    def undo(self, _event: tk.Event | None = None) -> None:
        if not self._history:
            return
        self._redo_stack.append(copy.deepcopy(self.mind_map.to_dict()))
        state = self._history.pop()
        self.mind_map = MindMap.from_dict(copy.deepcopy(state))
        self.selected_node_id = self.mind_map.root_id
        self.refresh()
        self._mark_dirty()

    def redo(self, _event: tk.Event | None = None) -> None:
        if not self._redo_stack:
            return
        self._history.append(copy.deepcopy(self.mind_map.to_dict()))
        state = self._redo_stack.pop()
        self.mind_map = MindMap.from_dict(copy.deepcopy(state))
        self.selected_node_id = self.mind_map.root_id
        self.refresh()
        self._mark_dirty()

    def new_map(self, _event: tk.Event | None = None) -> None:
        if self.mind_map.nodes() and not messagebox.askyesno("确认", "确定要新建并丢失当前更改吗？"):
            return
        self.mind_map = MindMap()
        self.selected_node_id = None
        self._history.clear()
        self._redo_stack.clear()
        self._ensure_root()
        self.current_file_path = None
        self._dirty = False
        self._cancel_autosave()
        self._update_window_title()

    def auto_layout(self, _event: tk.Event | None = None) -> None:
        if self.mind_map.root_id is None:
            return
        self._save_state()

        def layout(node_id: int, depth: int, y_offset: float) -> float:
            node = self.mind_map.get_node(node_id)
            x_position = 240 + depth * 240
            children = node.children
            if not children:
                node.x = x_position
                node.y = y_offset
                return y_offset + 140
            start_y = y_offset
            for child_id in children:
                y_offset = layout(child_id, depth + 1, y_offset)
            end_y = y_offset - 140
            node.x = x_position
            node.y = (start_y + end_y) / 2
            return y_offset

        layout(self.mind_map.root_id, 0, 160)
        self.refresh()
        self._mark_dirty()

    def choose_custom_color(self) -> None:
        initial = "#ffffff"
        if self.selected_node_id is not None:
            node = self.mind_map.get_node(self.selected_node_id)
            initial = node.color or initial
        color = colorchooser.askcolor(color=initial, title="选择颜色")
        if color and color[1]:
            self.set_color(color[1])

    def change_background(self) -> None:
        color = colorchooser.askcolor(color=self.mind_map.background, title="选择背景颜色")
        if not color or not color[1]:
            return
        self._save_state()
        self.mind_map.set_background(color[1])
        self.refresh()
        self._mark_dirty()

    def prompt_depth_limit(self) -> None:
        if self.mind_map.root_id is None:
            return
        depths = self._compute_depths()
        max_depth = max(depths.values(), default=0)
        kwargs: dict[str, int] = {"minvalue": 0}
        if max_depth > 0:
            kwargs["maxvalue"] = max_depth
        value = simpledialog.askinteger(
            "展开层级",
            "请输入要展开的最大层级（0 表示仅根节点）：",
            parent=self.root,
            **kwargs,
        )
        if value is None:
            return
        self.set_depth_limit(value)

    def set_depth_limit(self, depth: int | None) -> None:
        if depth is not None and depth < 0:
            depth = None
        self._depth_limit = depth
        self.refresh()

    def _ensure_depth_visible(self, node_id: int) -> None:
        if self._depth_limit is None:
            return
        depths = self._compute_depths()
        node_depth = depths.get(node_id)
        if node_depth is not None and node_depth > self._depth_limit:
            self._depth_limit = node_depth

    def _compute_depths(self) -> dict[int, int]:
        depths: dict[int, int] = {}
        if self.mind_map.root_id is None:
            return depths
        queue: deque[tuple[int, int]] = deque([(self.mind_map.root_id, 0)])
        while queue:
            node_id, depth = queue.popleft()
            if node_id in depths:
                continue
            depths[node_id] = depth
            node = self.mind_map.get_node(node_id)
            for child_id in node.children:
                queue.append((child_id, depth + 1))
        return depths

    def refresh(self, *, draw_selection: bool = True) -> None:
        self._clear_inline_editor()
        self.canvas.delete("all")
        self.canvas.config(bg=self.mind_map.background)
        depths = self._compute_depths()
        if self._depth_limit is None:
            visible_ids = set(depths.keys())
        else:
            visible_ids = {node_id for node_id, depth in depths.items() if depth <= self._depth_limit}
            if self.mind_map.root_id is not None:
                visible_ids.add(self.mind_map.root_id)
        self._visible_node_ids = visible_ids
        if self.selected_node_id is not None and self.selected_node_id not in visible_ids:
            current = self.selected_node_id
            while current is not None and current not in visible_ids:
                current_node = self.mind_map.get_node(current)
                current = current_node.parent_id
            self.selected_node_id = current

        search_text = self.search_var.get().strip().lower()
        highlighted: set[int] = set()
        if search_text:
            for node in self.mind_map.nodes():
                if search_text in node.label.lower() or search_text in node.note.lower():
                    highlighted.add(node.id)

        for node in self.mind_map.nodes():
            if node.id not in self._visible_node_ids:
                continue
            if node.parent_id is not None and node.parent_id in self._visible_node_ids:
                parent = self.mind_map.get_node(node.parent_id)
                px, py = self.to_screen(parent.x, parent.y)
                cx, cy = self.to_screen(node.x, node.y)
                self.canvas.create_line(
                    px,
                    py,
                    cx,
                    cy,
                    fill="#a0a0a0",
                    width=2,
                    smooth=True,
                )

        for node in self.mind_map.nodes():
            if node.id not in self._visible_node_ids:
                continue
            center_x, center_y = self.to_screen(node.x, node.y)
            radius_x = NODE_RADIUS_X * self.scale
            radius_y = NODE_RADIUS_Y * self.scale
            x0 = center_x - radius_x
            y0 = center_y - radius_y
            x1 = center_x + radius_x
            y1 = center_y + radius_y
            fill_color = node.color if node.color else "#ffffff"
            outline = "#ef476f" if node.id == self.selected_node_id else "#4a5568"
            if node.id in highlighted and node.id != self.selected_node_id:
                outline = "#118ab2"
            self.canvas.create_oval(x0, y0, x1, y1, fill=fill_color, outline=outline, width=2)
            font_size = max(int(12 * self.scale), 6)
            self.canvas.create_text(
                center_x,
                center_y,
                text=node.label if node.label else " ",
                font=("Helvetica", font_size, "bold"),
                width=max(radius_x * 2 - 10, 40),
            )
            if node.attachment:
                self.canvas.create_text(
                    center_x,
                    y1 + 14,
                    text="📎",
                    font=("Helvetica", max(int(12 * self.scale), 8)),
                )

        if draw_selection and self.selected_node_id is not None:
            node = self.mind_map.get_node(self.selected_node_id)
            if self.selected_node_id in self._visible_node_ids:
                center_x, center_y = self.to_screen(node.x, node.y)
                radius_x = NODE_RADIUS_X * self.scale
                radius_y = NODE_RADIUS_Y * self.scale
                self.canvas.create_oval(
                    center_x - radius_x - 4,
                    center_y - radius_y - 4,
                    center_x + radius_x + 4,
                    center_y + radius_y + 4,
                    outline="#118ab2",
                    width=2,
                    dash=(4, 2),
                )
            self._updating_note = True
            self.note_text.delete("1.0", tk.END)
            self.note_text.insert(tk.END, node.note)
            self._updating_note = False
            if node.attachment:
                self.attachment_var.set(f"附件：{node.attachment}")
            else:
                self.attachment_var.set("附件：无")
        elif self.selected_node_id is not None and not draw_selection:
            node = self.mind_map.get_node(self.selected_node_id)
            self._updating_note = True
            self.note_text.delete("1.0", tk.END)
            self.note_text.insert(tk.END, node.note)
            self._updating_note = False
            if node.attachment:
                self.attachment_var.set(f"附件：{node.attachment}")
            else:
                self.attachment_var.set("附件：无")
        else:
            self._updating_note = True
            self.note_text.delete("1.0", tk.END)
            self._updating_note = False
            self.attachment_var.set("附件：无")

    def _find_node_at(self, x: float, y: float) -> int | None:
        for node in reversed(self.mind_map.nodes()):
            if self._visible_node_ids and node.id not in self._visible_node_ids:
                continue
            if abs(node.x - x) <= NODE_RADIUS_X and abs(node.y - y) <= NODE_RADIUS_Y:
                return node.id
        return None


def run() -> None:
    root = tk.Tk()
    app = MindMapApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
