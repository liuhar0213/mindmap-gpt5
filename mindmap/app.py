"""Tkinter-based desktop mind map editor."""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from .model import MindMap, Node

NODE_RADIUS_X = 80
NODE_RADIUS_Y = 30


class MindMapApp:
    """A very small mind map editor built with Tkinter."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MindMap GPT5")
        self.mind_map = MindMap()
        self.selected_node_id: int | None = None
        self.dragging_node_id: int | None = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        self._build_ui()
        self._ensure_root()

    def _build_ui(self) -> None:
        self.root.geometry("1000x700")

        self.canvas = tk.Canvas(self.root, bg="#f2f3f5", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(self.root, width=240, bg="#ffffff", relief=tk.GROOVE, borderwidth=1)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)

        title = tk.Label(sidebar, text="工具", font=("Helvetica", 16, "bold"), bg="#ffffff")
        title.pack(pady=(20, 10))

        self.add_child_button = tk.Button(sidebar, text="添加子节点", command=self.add_child)
        self.add_child_button.pack(fill=tk.X, padx=20, pady=5)

        self.rename_button = tk.Button(sidebar, text="重命名节点", command=self.rename_selected)
        self.rename_button.pack(fill=tk.X, padx=20, pady=5)

        self.delete_button = tk.Button(sidebar, text="删除节点", command=self.delete_selected)
        self.delete_button.pack(fill=tk.X, padx=20, pady=5)

        tk.Label(sidebar, text="文件", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(pady=(30, 10))

        tk.Button(sidebar, text="保存", command=self.save_to_file).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="打开", command=self.load_from_file).pack(fill=tk.X, padx=20, pady=5)

        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

    def _ensure_root(self) -> None:
        if self.mind_map.root_id is None:
            node = self.mind_map.create_root()
            self.selected_node_id = node.id
            self.refresh()

    def add_child(self) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个父节点")
            return
        label = simpledialog.askstring("添加节点", "请输入节点内容", parent=self.root)
        if label is None:
            return
        if not label.strip():
            label = "新主题"
        node = self.mind_map.add_child(self.selected_node_id, label.strip())
        self.selected_node_id = node.id
        self.refresh()

    def rename_selected(self) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个节点")
            return
        node = self.mind_map.get_node(self.selected_node_id)
        label = simpledialog.askstring("重命名节点", "请输入新的名称", initialvalue=node.label, parent=self.root)
        if label is None:
            return
        if not label.strip():
            messagebox.showwarning("警告", "名称不能为空")
            return
        self.mind_map.rename_node(node.id, label.strip())
        self.refresh()

    def delete_selected(self) -> None:
        if self.selected_node_id is None:
            return
        if self.selected_node_id == self.mind_map.root_id:
            messagebox.showwarning("警告", "不能删除根节点")
            return
        if messagebox.askyesno("确认", "确定要删除选中的节点及其子节点吗？"):
            self.mind_map.delete_node(self.selected_node_id)
            self.selected_node_id = self.mind_map.root_id
            self.refresh()

    def save_to_file(self) -> None:
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            title="保存思维导图",
        )
        if not file_path:
            return
        data = self.mind_map.to_dict()
        Path(file_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("保存成功", "思维导图已保存")

    def load_from_file(self) -> None:
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
            self.refresh()
        except Exception as exc:  # pragma: no cover - Tkinter message box
            messagebox.showerror("错误", f"加载文件失败: {exc}")

    def on_canvas_click(self, event: tk.Event[tk.Canvas]) -> None:
        node_id = self._find_node_at(event.x, event.y)
        if node_id is not None:
            self.selected_node_id = node_id
            node = self.mind_map.get_node(node_id)
            self.dragging_node_id = node_id
            self.drag_offset_x = node.x - event.x
            self.drag_offset_y = node.y - event.y
        else:
            self.selected_node_id = None
        self.refresh()

    def on_canvas_drag(self, event: tk.Event[tk.Canvas]) -> None:
        if self.dragging_node_id is None:
            return
        new_x = event.x + self.drag_offset_x
        new_y = event.y + self.drag_offset_y
        self.mind_map.move_node(self.dragging_node_id, new_x, new_y)
        self.refresh(draw_selection=False)

    def on_canvas_release(self, _event: tk.Event[tk.Canvas]) -> None:
        self.dragging_node_id = None

    def refresh(self, *, draw_selection: bool = True) -> None:
        self.canvas.delete("all")
        for node in self.mind_map.nodes():
            if node.parent_id is not None:
                parent = self.mind_map.get_node(node.parent_id)
                self.canvas.create_line(
                    parent.x,
                    parent.y,
                    node.x,
                    node.y,
                    fill="#a0a0a0",
                    width=2,
                    smooth=True,
                )

        for node in self.mind_map.nodes():
            x0 = node.x - NODE_RADIUS_X
            y0 = node.y - NODE_RADIUS_Y
            x1 = node.x + NODE_RADIUS_X
            y1 = node.y + NODE_RADIUS_Y
            fill_color = "#ffd166" if node.id == self.selected_node_id else "#ffffff"
            outline = "#ef476f" if node.id == self.selected_node_id else "#4a5568"
            self.canvas.create_oval(x0, y0, x1, y1, fill=fill_color, outline=outline, width=2)
            self.canvas.create_text(node.x, node.y, text=node.label, font=("Helvetica", 12, "bold"))

        if draw_selection and self.selected_node_id is not None:
            node = self.mind_map.get_node(self.selected_node_id)
            self.canvas.create_oval(
                node.x - NODE_RADIUS_X - 4,
                node.y - NODE_RADIUS_Y - 4,
                node.x + NODE_RADIUS_X + 4,
                node.y + NODE_RADIUS_Y + 4,
                outline="#118ab2",
                width=2,
                dash=(4, 2),
            )

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
