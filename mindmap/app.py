"""Tkinter-based desktop mind map editor."""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

try:  # pragma: no cover - fallback for running as a script
    from .model import MindMap, Node
except ImportError:  # pragma: no cover - executed when launched via ``python app.py``
    from model import MindMap, Node

NODE_RADIUS_X = 80
NODE_RADIUS_Y = 30
TABLE_CELL_WIDTH = 90
TABLE_CELL_HEIGHT = 40
DEFAULT_IMAGE_MAX_SIZE = 240


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

        self._image_cache: dict[int, tk.PhotoImage] = {}
        self._build_ui()
        self._ensure_root()

    def _build_ui(self) -> None:
        self.root.geometry("1200x800")

        canvas_frame = tk.Frame(self.root)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg="#f2f3f5",
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        v_scroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

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

        tk.Label(sidebar, text="插入", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(pady=(20, 10))
        tk.Button(sidebar, text="插入表格", command=self.add_table).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="插入图片", command=self.add_image).pack(fill=tk.X, padx=20, pady=5)

        tk.Label(sidebar, text="文件", font=("Helvetica", 16, "bold"), bg="#ffffff").pack(pady=(30, 10))

        tk.Button(sidebar, text="保存", command=self.save_to_file).pack(fill=tk.X, padx=20, pady=5)
        tk.Button(sidebar, text="打开", command=self.load_from_file).pack(fill=tk.X, padx=20, pady=5)

        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)
        self.canvas.bind("<ButtonPress-2>", self._start_pan)
        self.canvas.bind("<B2-Motion>", self._pan_canvas)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel_linux)
        self.canvas.bind("<Button-5>", self._on_mousewheel_linux)

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

    def add_table(self) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个父节点")
            return

        title = simpledialog.askstring("插入表格", "请输入表格名称", parent=self.root)
        if title is None:
            return
        title = title.strip() or "新表格"

        rows = simpledialog.askinteger("表格行数", "请输入行数 (1-10)", parent=self.root, minvalue=1, maxvalue=10)
        if rows is None:
            return
        cols = simpledialog.askinteger("表格列数", "请输入列数 (1-10)", parent=self.root, minvalue=1, maxvalue=10)
        if cols is None:
            return

        cells = [["" for _ in range(cols)] for _ in range(rows)]
        metadata = {"rows": rows, "cols": cols, "cells": cells}
        node = self.mind_map.add_child(
            self.selected_node_id,
            title,
            content_type="table",
            metadata=metadata,
        )
        self.selected_node_id = node.id
        self.refresh()

    def add_image(self) -> None:
        if self.selected_node_id is None:
            messagebox.showinfo("提示", "请选择一个父节点")
            return

        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.png *.gif *.ppm *.pgm"),
                ("PNG", "*.png"),
                ("GIF", "*.gif"),
                ("PPM/PGM", "*.ppm *.pgm"),
            ],
        )
        if not file_path:
            return

        try:
            image = tk.PhotoImage(file=file_path)
        except tk.TclError as exc:  # pragma: no cover - Tkinter message box
            messagebox.showerror("错误", f"无法加载图片: {exc}")
            return

        divisor = 1
        while image.width() / divisor > DEFAULT_IMAGE_MAX_SIZE or image.height() / divisor > DEFAULT_IMAGE_MAX_SIZE:
            divisor += 1
        if divisor > 1:
            image = image.subsample(divisor, divisor)

        metadata = {
            "path": file_path,
            "display_width": image.width(),
            "display_height": image.height(),
            "subsample": divisor,
        }
        label = Path(file_path).stem
        node = self.mind_map.add_child(
            self.selected_node_id,
            label,
            content_type="image",
            metadata=metadata,
        )
        self._image_cache[node.id] = image
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
            self._image_cache = {}
            self.selected_node_id = self.mind_map.root_id
            self.refresh()
        except Exception as exc:  # pragma: no cover - Tkinter message box
            messagebox.showerror("错误", f"加载文件失败: {exc}")

    def on_canvas_click(self, event: tk.Event[tk.Canvas]) -> None:
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        node_id = self._find_node_at(canvas_x, canvas_y)
        if node_id is not None:
            self.selected_node_id = node_id
            node = self.mind_map.get_node(node_id)
            self.dragging_node_id = node_id
            self.drag_offset_x = node.x - canvas_x
            self.drag_offset_y = node.y - canvas_y
        else:
            self.selected_node_id = None
        self.refresh()

    def on_canvas_drag(self, event: tk.Event[tk.Canvas]) -> None:
        if self.dragging_node_id is None:
            return
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        new_x = canvas_x + self.drag_offset_x
        new_y = canvas_y + self.drag_offset_y
        self.mind_map.move_node(self.dragging_node_id, new_x, new_y)
        self.refresh(draw_selection=False)

    def on_canvas_release(self, _event: tk.Event[tk.Canvas]) -> None:
        self.dragging_node_id = None

    def refresh(self, *, draw_selection: bool = True) -> None:
        nodes = self.mind_map.nodes()
        self.canvas.delete("all")
        valid_ids = {node.id for node in nodes}
        self._image_cache = {node_id: img for node_id, img in self._image_cache.items() if node_id in valid_ids}

        for node in nodes:
            if node.parent_id is not None and node.parent_id in valid_ids:
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

        for node in nodes:
            self._draw_node(node)

        if draw_selection and self.selected_node_id is not None and self.selected_node_id in valid_ids:
            node = self.mind_map.get_node(self.selected_node_id)
            self._draw_selection(node)

        self._update_scroll_region(nodes)

    def _find_node_at(self, x: float, y: float) -> int | None:
        for node in reversed(self.mind_map.nodes()):
            x0, y0, x1, y1 = self._node_bounds(node)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return node.id
        return None

    def on_canvas_double_click(self, event: tk.Event[tk.Canvas]) -> None:
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        node_id = self._find_node_at(canvas_x, canvas_y)
        if node_id is None:
            return
        self.selected_node_id = node_id
        node = self.mind_map.get_node(node_id)
        if node.content_type == "table":
            self._open_table_editor(node)
        elif node.content_type == "image":
            self._open_image_viewer(node)
        else:
            self.rename_selected()

    def _draw_node(self, node: Node) -> None:
        if node.content_type == "table":
            self._draw_table_node(node)
        elif node.content_type == "image":
            self._draw_image_node(node)
        else:
            fill_color = "#ffd166" if node.id == self.selected_node_id else "#ffffff"
            outline = "#ef476f" if node.id == self.selected_node_id else "#4a5568"
            self.canvas.create_oval(
                node.x - NODE_RADIUS_X,
                node.y - NODE_RADIUS_Y,
                node.x + NODE_RADIUS_X,
                node.y + NODE_RADIUS_Y,
                fill=fill_color,
                outline=outline,
                width=2,
            )
            self.canvas.create_text(node.x, node.y, text=node.label, font=("Helvetica", 12, "bold"))

    def _draw_selection(self, node: Node) -> None:
        if node.content_type == "text":
            self.canvas.create_oval(
                node.x - NODE_RADIUS_X - 4,
                node.y - NODE_RADIUS_Y - 4,
                node.x + NODE_RADIUS_X + 4,
                node.y + NODE_RADIUS_Y + 4,
                outline="#118ab2",
                width=2,
                dash=(4, 2),
            )
        else:
            x0, y0, x1, y1 = self._node_bounds(node)
            self.canvas.create_rectangle(
                x0 - 4,
                y0 - 4,
                x1 + 4,
                y1 + 4,
                outline="#118ab2",
                width=2,
                dash=(4, 2),
            )

    def _draw_table_node(self, node: Node) -> None:
        rows = max(1, int(node.metadata.get("rows", 1)))
        cols = max(1, int(node.metadata.get("cols", 1)))
        x0, y0, x1, y1 = self._node_bounds(node)
        header_height = 40
        table_y0 = y0 + header_height

        self.canvas.create_rectangle(x0, y0, x1, y1, fill="#ffffff", outline="#4a5568", width=2)
        self.canvas.create_rectangle(x0, y0, x1, table_y0, fill="#ffd166", outline="")
        self.canvas.create_text(node.x, y0 + header_height / 2, text=node.label, font=("Helvetica", 12, "bold"))

        table_height = max(y1 - table_y0, TABLE_CELL_HEIGHT)
        table_width = max(x1 - x0, TABLE_CELL_WIDTH)
        cell_height = table_height / rows
        cell_width = table_width / cols

        for row in range(1, rows):
            line_y = table_y0 + row * cell_height
            self.canvas.create_line(x0, line_y, x1, line_y, fill="#cbd5e0")

        for col in range(1, cols):
            line_x = x0 + col * cell_width
            self.canvas.create_line(line_x, table_y0, line_x, y1, fill="#cbd5e0")

        cells = node.metadata.get("cells", [])
        for row in range(rows):
            for col in range(cols):
                cell_text = ""
                if row < len(cells) and col < len(cells[row]):
                    cell_text = str(cells[row][col])
                text_x = x0 + col * cell_width + cell_width / 2
                text_y = table_y0 + row * cell_height + cell_height / 2
                self.canvas.create_text(
                    text_x,
                    text_y,
                    text=cell_text,
                    font=("Helvetica", 11),
                    width=cell_width - 10,
                )

    def _draw_image_node(self, node: Node) -> None:
        x0, y0, x1, y1 = self._node_bounds(node)
        header_height = 40
        image_area_y0 = y0 + header_height
        image_area_y1 = y1

        self.canvas.create_rectangle(x0, y0, x1, y1, fill="#ffffff", outline="#4a5568", width=2)
        self.canvas.create_rectangle(x0, y0, x1, image_area_y0, fill="#ffd166", outline="")
        self.canvas.create_text(node.x, y0 + header_height / 2, text=node.label, font=("Helvetica", 12, "bold"))

        image = self._load_image(node)
        if image is not None:
            self.canvas.create_image(
                node.x,
                image_area_y0 + (image_area_y1 - image_area_y0) / 2,
                image=image,
            )
        else:
            self.canvas.create_text(
                node.x,
                image_area_y0 + (image_area_y1 - image_area_y0) / 2,
                text="图片缺失",
                font=("Helvetica", 11, "italic"),
                fill="#ef476f",
            )

    def _update_scroll_region(self, nodes: list[Node]) -> None:
        if not nodes:
            self.canvas.configure(scrollregion=(0, 0, 2000, 2000))
            return

        x_values = []
        y_values = []
        for node in nodes:
            x0, y0, x1, y1 = self._node_bounds(node)
            x_values.extend([x0, x1])
            y_values.extend([y0, y1])

        margin = 400
        min_x = min(x_values) - margin
        max_x = max(x_values) + margin
        min_y = min(y_values) - margin
        max_y = max(y_values) + margin
        self.canvas.configure(scrollregion=(min_x, min_y, max_x, max_y))

    def _node_bounds(self, node: Node) -> tuple[float, float, float, float]:
        if node.content_type == "table":
            rows = max(1, int(node.metadata.get("rows", 1)))
            cols = max(1, int(node.metadata.get("cols", 1)))
            table_width = max(TABLE_CELL_WIDTH * cols, NODE_RADIUS_X * 2)
            table_height = max(TABLE_CELL_HEIGHT * rows, NODE_RADIUS_Y * 2)
            total_height = table_height + 40
            return (
                node.x - table_width / 2,
                node.y - total_height / 2,
                node.x + table_width / 2,
                node.y + total_height / 2,
            )
        if node.content_type == "image":
            width = max(int(node.metadata.get("display_width", NODE_RADIUS_X * 2)), NODE_RADIUS_X * 2)
            height = max(int(node.metadata.get("display_height", NODE_RADIUS_Y * 2)), NODE_RADIUS_Y * 2)
            total_height = height + 40
            return (
                node.x - width / 2,
                node.y - total_height / 2,
                node.x + width / 2,
                node.y + total_height / 2,
            )
        return (
            node.x - NODE_RADIUS_X,
            node.y - NODE_RADIUS_Y,
            node.x + NODE_RADIUS_X,
            node.y + NODE_RADIUS_Y,
        )

    def _load_image(self, node: Node) -> tk.PhotoImage | None:
        if node.id in self._image_cache:
            return self._image_cache[node.id]

        path = node.metadata.get("path")
        if not path:
            return None
        try:
            image = tk.PhotoImage(file=path)
        except tk.TclError:
            return None

        divisor = max(1, int(node.metadata.get("subsample", 1)))
        if divisor > 1:
            image = image.subsample(divisor, divisor)

        self._image_cache[node.id] = image
        node.metadata["display_width"] = image.width()
        node.metadata["display_height"] = image.height()
        return image

    def _open_table_editor(self, node: Node) -> None:
        rows = max(1, int(node.metadata.get("rows", 1)))
        cols = max(1, int(node.metadata.get("cols", 1)))
        cells = node.metadata.get("cells", [])

        editor = tk.Toplevel(self.root)
        editor.title(f"编辑表格 - {node.label}")
        editor.grab_set()

        grid_frame = tk.Frame(editor, padx=10, pady=10)
        grid_frame.pack()

        entries: list[list[tk.Entry]] = []
        for row in range(rows):
            row_entries: list[tk.Entry] = []
            for col in range(cols):
                entry = tk.Entry(grid_frame, width=15)
                entry.grid(row=row, column=col, padx=3, pady=3)
                if row < len(cells) and col < len(cells[row]):
                    entry.insert(0, str(cells[row][col]))
                row_entries.append(entry)
            entries.append(row_entries)

        button_frame = tk.Frame(editor, pady=10)
        button_frame.pack()

        def save_table() -> None:
            new_cells = [[entry.get() for entry in row_entries] for row_entries in entries]
            metadata = dict(node.metadata)
            metadata.update({"rows": rows, "cols": cols, "cells": new_cells})
            self.mind_map.update_metadata(node.id, metadata)
            editor.destroy()
            self.refresh()

        def cancel() -> None:
            editor.destroy()

        tk.Button(button_frame, text="保存", command=save_table).pack(side=tk.LEFT, padx=10)
        tk.Button(button_frame, text="取消", command=cancel).pack(side=tk.LEFT, padx=10)

    def _open_image_viewer(self, node: Node) -> None:
        image = self._load_image(node)
        if image is None:
            messagebox.showerror("提示", "图片无法显示，请确认文件路径是否存在")
            return

        viewer = tk.Toplevel(self.root)
        viewer.title(f"查看图片 - {node.label}")
        viewer.grab_set()

        tk.Label(viewer, text=node.metadata.get("path", ""), pady=6).pack()
        label = tk.Label(viewer, image=image, bd=0)
        label.image = image
        label.pack(padx=10, pady=10)

    def _start_pan(self, event: tk.Event[tk.Canvas]) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def _pan_canvas(self, event: tk.Event[tk.Canvas]) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_mousewheel(self, event: tk.Event[tk.Canvas]) -> None:
        if event.delta == 0:
            return
        steps = -1 if event.delta > 0 else 1
        if abs(event.delta) > 120:
            steps *= abs(event.delta) // 120
        if event.state & 0x0001:  # Shift pressed
            self.canvas.xview_scroll(steps, "units")
        else:
            self.canvas.yview_scroll(steps, "units")

    def _on_shift_mousewheel(self, event: tk.Event[tk.Canvas]) -> None:
        if event.delta == 0:
            return
        steps = -1 if event.delta > 0 else 1
        if abs(event.delta) > 120:
            steps *= abs(event.delta) // 120
        self.canvas.xview_scroll(steps, "units")

    def _on_mousewheel_linux(self, event: tk.Event[tk.Canvas]) -> None:
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")


def run() -> None:
    root = tk.Tk()
    app = MindMapApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
