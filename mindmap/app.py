"""Tkinter-based desktop mind map editor."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

try:  # pragma: no cover - fallback for running as a script
    from .model import MindMap, Node
except ImportError:  # pragma: no cover - executed when launched via ``python app.py``
    from model import MindMap, Node

NODE_RADIUS_X = 80
NODE_RADIUS_Y = 30
MAX_HISTORY = 50
AUTOSAVE_DELAY_MS = 1500
COLOR_PALETTE = [
    "#ffd166",
    "#06d6a0",
    "#118ab2",
    "#ef476f",
    "#9b5de5",
    "#f4a261",
    "#48cae4",
    "#ede7b1",
]


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

        self._build_ui()
        self._ensure_root()
        self._maybe_restore_autosave()
        self._update_window_title()

    def _build_ui(self) -> None:
        self.root.geometry("1200x750")

        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="新建", command=self.new_map, accelerator="Ctrl+N")
        file_menu.add_command(label="打开", command=self.load_from_file, accelerator="Ctrl+O")
        file_menu.add_command(label="保存", command=self.save_to_file, accelerator="Ctrl+S")
        export_menu = tk.Menu(file_menu, tearoff=False)
        export_menu.add_command(label="导出为 Markdown", command=self.export_markdown)
        export_menu.add_command(label="导出为文本", command=self.export_text)
        export_menu.add_command(label="导出为 JSON", command=self.export_json_copy)
        file_menu.add_cascade(label="导出", menu=export_menu)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit, accelerator="Ctrl+Q")
        menubar.add_cascade(label="文件", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="撤销", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="重做", command=self.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="添加子节点", command=self.add_child, accelerator="Ctrl+Enter")
        edit_menu.add_command(label="添加兄弟节点", command=self.add_sibling, accelerator="Shift+Enter")
        edit_menu.add_command(label="重命名", command=self.rename_selected, accelerator="F2")
        edit_menu.add_command(label="删除", command=self.delete_selected, accelerator="Delete")
        menubar.add_cascade(label="编辑", menu=edit_menu)

        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="自动排版", command=self.auto_layout, accelerator="Ctrl+L")
        menubar.add_cascade(label="工具", menu=tools_menu)

        self.root.config(menu=menubar)

        self.canvas = tk.Canvas(self.root, bg="#f2f3f5", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(self.root, width=280, bg="#ffffff", relief=tk.GROOVE, borderwidth=1)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)

        title = tk.Label(sidebar, text="工具", font=("Helvetica", 16, "bold"), bg="#ffffff")
        title.pack(pady=(20, 10))

        tk.Button(sidebar, text="添加子节点 (Ctrl+Enter)", command=self.add_child).pack(
            fill=tk.X, padx=20, pady=5
        )
        tk.Button(sidebar, text="添加兄弟节点 (Shift+Enter)", command=self.add_sibling).pack(
            fill=tk.X, padx=20, pady=5
        )
        tk.Button(sidebar, text="重命名 (F2)", command=self.rename_selected).pack(
            fill=tk.X, padx=20, pady=5
        )
        tk.Button(sidebar, text="删除 (Del)", command=self.delete_selected).pack(
            fill=tk.X, padx=20, pady=5
        )
        tk.Button(sidebar, text="撤销 (Ctrl+Z)", command=self.undo).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="重做 (Ctrl+Y)", command=self.redo).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="自动排版 (Ctrl+L)", command=self.auto_layout).pack(
            fill=tk.X, padx=20, pady=5
        )

        tk.Label(sidebar, text="搜索 (Ctrl+F)", font=("Helvetica", 14, "bold"), bg="#ffffff").pack(
            pady=(20, 5)
        )
        search_entry = tk.Entry(sidebar, textvariable=self.search_var)
        search_entry.pack(fill=tk.X, padx=20)
        self._search_entry = search_entry

        tk.Label(sidebar, text="文件", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(
            pady=(30, 10)
        )
        tk.Button(sidebar, text="保存", command=self.save_to_file).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="打开", command=self.load_from_file).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="新建", command=self.new_map).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="插入文件", command=self.attach_file).pack(fill=tk.X, padx=20, pady=5)

        tk.Label(sidebar, text="颜色", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(
            pady=(30, 10)
        )
        palette_frame = tk.Frame(sidebar, bg="#ffffff")
        palette_frame.pack(padx=20, fill=tk.X)
        for idx, color in enumerate(COLOR_PALETTE):
            btn = tk.Button(
                palette_frame,
                bg=color,
                width=2,
                relief=tk.RIDGE,
                command=lambda c=color: self.set_color(c),
            )
            btn.grid(row=idx // 4, column=idx % 4, padx=4, pady=4, sticky="nsew")

        tk.Label(sidebar, text="备注", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(
            pady=(30, 5)
        )
        self.note_text = tk.Text(sidebar, height=10, wrap="word", relief=tk.SUNKEN, borderwidth=1)
        self.note_text.pack(fill=tk.BOTH, expand=False, padx=20)
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

        self.context_menu = tk.Menu(self.root, tearoff=False)
        self.context_menu.add_command(label="添加子节点", command=self.add_child)
        self.context_menu.add_command(label="添加兄弟节点", command=self.add_sibling)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="重命名", command=self.rename_selected)
        self.context_menu.add_command(label="删除", command=self.delete_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="插入文件", command=self.attach_file)
        self.context_menu.add_command(label="打开附件", command=self.open_attachment)
        self.context_menu.add_command(label="移除附件", command=self.remove_attachment)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="自动排版", command=self.auto_layout)

        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<Control-MouseWheel>", self.on_zoom)
        self.canvas.bind("<Control-Button-4>", lambda event: self.on_zoom(event, delta=120))
        self.canvas.bind("<Control-Button-5>", lambda event: self.on_zoom(event, delta=-120))

        self.root.bind("<Control-s>", self.save_to_file)
        self.root.bind("<Control-o>", self.load_from_file)
        self.root.bind("<Control-n>", self.new_map)
        self.root.bind("<Control-q>", lambda _event: self.root.quit())
        self.root.bind("<Control-z>", self.undo)
        self.root.bind("<Control-y>", self.redo)
        self.root.bind("<Control-l>", self.auto_layout)
        self.root.bind("<Control-Return>", self.add_child)
        self.root.bind("<Shift-Return>", self.add_sibling)
        self.root.bind_all("<Return>", self.quick_add_sibling)
        self.root.bind_all("<Tab>", self.quick_add_child)
        self.root.bind("<F2>", self.rename_selected)
        self.root.bind("<Delete>", self.delete_selected)
        self.root.bind("<Control-f>", self.focus_search)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _ensure_root(self) -> None:
        if self.mind_map.root_id is None:
            node = self.mind_map.create_root()
            self.selected_node_id = node.id
            self._history.clear()
            self._redo_stack.clear()
            self._history.append(copy.deepcopy(self.mind_map.to_dict()))
            self.refresh()
        else:
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
        label = simpledialog.askstring("添加节点", "请输入节点内容", parent=self.root)
        if label is None:
            return
        if not label.strip():
            label = "新主题"
        self._save_state()
        node = self.mind_map.add_child(self.selected_node_id, label.strip())
        self.selected_node_id = node.id
        self.refresh()
        self._mark_dirty()

    def add_sibling(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个节点")
            return
        try:
            label = simpledialog.askstring("添加兄弟节点", "请输入节点内容", parent=self.root)
            if label is None:
                return
            if not label.strip():
                label = "新主题"
            self._save_state()
            node = self.mind_map.add_sibling(self.selected_node_id, label.strip())
            self.selected_node_id = node.id
            self.refresh()
            self._mark_dirty()
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))

    def rename_selected(self, _event: tk.Event | None = None) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个节点")
            return
        node = self.mind_map.get_node(self.selected_node_id)
        label = simpledialog.askstring(
            "重命名节点", "请输入新的名称", initialvalue=node.label, parent=self.root
        )
        if label is None:
            return
        if not label.strip():
            messagebox.showwarning("警告", "名称不能为空")
            return
        self._save_state()
        self.mind_map.rename_node(node.id, label.strip())
        self.refresh()
        self._mark_dirty()

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
        if not node.label or node.label == "新主题":
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

    def quick_add_child(self, event: tk.Event | None = None) -> str | None:
        if event is not None and (event.state & (0x1 | 0x4 | 0x8)):
            return None
        focus_widget = self.root.focus_get()
        if focus_widget not in {None, self.canvas}:
            return None
        if self.selected_node_id is None:
            return "break"
        self._save_state()
        node = self.mind_map.add_child(self.selected_node_id, "新主题")
        self.selected_node_id = node.id
        self.refresh()
        self._mark_dirty()
        return "break"

    def quick_add_sibling(self, event: tk.Event | None = None) -> str | None:
        if event is not None and (event.state & (0x1 | 0x4 | 0x8)):
            return None
        focus_widget = self.root.focus_get()
        if focus_widget not in {None, self.canvas}:
            return None
        if self.selected_node_id is None:
            return "break"
        try:
            self._save_state()
            node = self.mind_map.add_sibling(self.selected_node_id, "新主题")
            self.selected_node_id = node.id
            self.refresh()
            self._mark_dirty()
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))
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
        else:
            self.context_menu.entryconfig("打开附件", state=tk.DISABLED)
            self.context_menu.entryconfig("移除附件", state=tk.DISABLED)
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

    def refresh(self, *, draw_selection: bool = True) -> None:
        self.canvas.delete("all")
        search_text = self.search_var.get().strip().lower()
        highlighted: set[int] = set()
        if search_text:
            for node in self.mind_map.nodes():
                if search_text in node.label.lower() or search_text in node.note.lower():
                    highlighted.add(node.id)

        for node in self.mind_map.nodes():
            if node.parent_id is not None:
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
                text=node.label,
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
        elif not draw_selection:
            # ensure note panel stays in sync even when skipping selection highlight
            if self.selected_node_id is not None:
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
            self.attachment_var.set("附件：无")

    def _find_node_at(self, x: float, y: float) -> int | None:
        for node in reversed(self.mind_map.nodes()):
            if abs(node.x - x) <= NODE_RADIUS_X and abs(node.y - y) <= NODE_RADIUS_Y:
                return node.id
        return None


def run() -> None:
    root = tk.Tk()
    app = MindMapApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
