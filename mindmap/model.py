"""Mind map data structures and serialization utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Node:
    """A single node in the mind map."""

    id: int
    label: str
    x: float
    y: float
    parent_id: Optional[int] = None
    children: List[int] = field(default_factory=list)
    content_type: str = "text"
    metadata: Dict[str, Any] = field(default_factory=dict)


class MindMap:
    """Simple in-memory representation of a mind map."""

    def __init__(self) -> None:
        self._nodes: Dict[int, Node] = {}
        self._next_id = 1
        self.root_id: Optional[int] = None

    def create_root(self, label: str = "Central Idea") -> Node:
        if self.root_id is not None:
            raise ValueError("Root node already exists")
        node = self._create_node(label, 400, 300, None)
        self.root_id = node.id
        return node

    def add_child(
        self,
        parent_id: int,
        label: str = "New Topic",
        *,
        content_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Node:
        parent = self._nodes[parent_id]
        x_offset = 160 if len(parent.children) % 2 == 0 else -160
        y_offset = (len(parent.children) // 2 + 1) * 80
        node = self._create_node(
            label,
            parent.x + x_offset,
            parent.y + y_offset,
            parent_id,
            content_type=content_type,
            metadata=metadata or {},
        )
        parent.children.append(node.id)
        return node

    def delete_node(self, node_id: int) -> None:
        if node_id not in self._nodes:
            return
        if node_id == self.root_id:
            raise ValueError("Cannot delete the root node")

        node = self._nodes[node_id]
        parent = self._nodes.get(node.parent_id) if node.parent_id else None
        if parent:
            parent.children = [child for child in parent.children if child != node_id]

        # Recursively delete descendants
        for child_id in list(node.children):
            self.delete_node(child_id)

        del self._nodes[node_id]

    def move_node(self, node_id: int, x: float, y: float) -> None:
        self._nodes[node_id].x = x
        self._nodes[node_id].y = y

    def rename_node(self, node_id: int, label: str) -> None:
        self._nodes[node_id].label = label

    def get_node(self, node_id: int) -> Node:
        return self._nodes[node_id]

    def nodes(self) -> List[Node]:
        return list(self._nodes.values())

    def to_dict(self) -> Dict:
        return {
            "root_id": self.root_id,
            "next_id": self._next_id,
            "nodes": {
                node_id: {
                    "label": node.label,
                    "x": node.x,
                    "y": node.y,
                    "parent_id": node.parent_id,
                    "children": node.children,
                    "content_type": node.content_type,
                    "metadata": node.metadata,
                }
                for node_id, node in self._nodes.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "MindMap":
        instance = cls()
        instance.root_id = data.get("root_id")
        instance._next_id = data.get("next_id", 1)

        nodes: Dict[int, Node] = {}
        for node_id_str, node_data in data.get("nodes", {}).items():
            node_id = int(node_id_str)
            nodes[node_id] = Node(
                id=node_id,
                label=node_data["label"],
                x=node_data["x"],
                y=node_data["y"],
                parent_id=node_data.get("parent_id"),
                children=list(node_data.get("children", [])),
                content_type=node_data.get("content_type", "text"),
                metadata=dict(node_data.get("metadata", {})),
            )

        instance._nodes = nodes
        return instance

    def _create_node(
        self,
        label: str,
        x: float,
        y: float,
        parent_id: Optional[int],
        *,
        content_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Node:
        node_id = self._next_id
        self._next_id += 1
        node = Node(
            id=node_id,
            label=label,
            x=x,
            y=y,
            parent_id=parent_id,
            content_type=content_type,
            metadata=dict(metadata or {}),
        )
        self._nodes[node_id] = node
        return node

    def update_metadata(self, node_id: int, metadata: Dict[str, Any]) -> None:
        self._nodes[node_id].metadata = dict(metadata)
