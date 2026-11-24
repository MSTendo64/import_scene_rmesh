"""Pure-Python reader for SCP: Containment Breach .rmesh files.

This module intentionally has no Kaitai or other third-party dependencies.
The binary layout follows the original Kaitai-generated reader.
"""
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
import io
import math
import struct


class RMeshFormatError(ValueError):
    """Raised when an RMesh file is truncated or structurally invalid."""


class TextureType(IntEnum):
    none = 0
    opaque = 1
    lightmap = 2
    transparent = 3


class _Reader:
    MAX_ITEMS = 2_000_000
    MAX_STRING_BYTES = 16 * 1024 * 1024

    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.size = len(data)

    @property
    def remaining(self):
        return self.size - self.stream.tell()

    def read(self, size):
        if size < 0 or size > self.remaining:
            raise RMeshFormatError(
                f"Unexpected end of RMesh file at offset 0x{self.stream.tell():X}"
            )
        value = self.stream.read(size)
        if len(value) != size:
            raise RMeshFormatError("Unexpected end of RMesh file")
        return value

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        try:
            return struct.unpack(fmt, self.read(size))
        except struct.error as exc:
            raise RMeshFormatError(str(exc)) from exc

    def u8(self):
        return self.unpack("<B")[0]

    def u32(self):
        return self.unpack("<I")[0]

    def i32(self):
        return self.unpack("<i")[0]

    def f32(self):
        value = self.unpack("<f")[0]
        if not math.isfinite(value):
            raise RMeshFormatError("RMesh contains a non-finite floating-point value")
        return value

    def count(self, label, minimum_item_size=1):
        count = self.u32()
        if count > self.MAX_ITEMS:
            raise RMeshFormatError(f"{label} count is unreasonably large: {count}")
        if minimum_item_size and count > self.remaining // minimum_item_size:
            raise RMeshFormatError(
                f"{label} count ({count}) exceeds the remaining file data"
            )
        return count

    def string(self):
        length = self.u32()
        if length > self.MAX_STRING_BYTES:
            raise RMeshFormatError(f"String is too large: {length} bytes")
        try:
            return self.read(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RMeshFormatError(f"Invalid UTF-8 string at offset {self.stream.tell() - length}") from exc

    def v2(self):
        return SimpleNamespace(x=self.f32(), y=self.f32())

    def v3(self):
        return SimpleNamespace(x=self.f32(), y=self.f32(), z=self.f32())

    def v3i(self):
        return SimpleNamespace(x=self.u32(), y=self.u32(), z=self.u32())

    def color(self):
        r, g, b = self.unpack("<BBB")
        return SimpleNamespace(r=r, g=g, b=b)

    def vertex(self):
        return SimpleNamespace(
            position=self.v3(), uv1=self.v2(), uv2=self.v2(), color=self.color()
        )

    def texture(self):
        raw_type = self.u8()
        try:
            texture_type = TextureType(raw_type)
        except ValueError:
            texture_type = raw_type
        return SimpleNamespace(mat_type=SimpleNamespace(value=texture_type),
                               texture_name=SimpleNamespace(value=self.string()))

    def submesh(self):
        textures = [self.texture(), self.texture()]
        vertex_count = self.count("Vertex", 31)
        vertices = [self.vertex() for _ in range(vertex_count)]
        index_count = self.count("Triangle", 12)
        indices = [self.v3i() for _ in range(index_count)]
        return SimpleNamespace(textures=textures, vertex_count=vertex_count,
                               vertices=vertices, index_count=index_count,
                               indices=indices)

    def box(self):
        vertex_count = self.count("Trigger box vertex", 12)
        vertices = [self.v3() for _ in range(vertex_count)]
        index_count = self.count("Trigger box triangle", 12)
        indices = [self.v3i() for _ in range(index_count)]
        return SimpleNamespace(vertex_count=vertex_count, vertices=vertices,
                               index_count=index_count, indices=indices)

    def triggerbox(self):
        box_count = self.count("Trigger box", 8)
        boxes = [self.box() for _ in range(box_count)]
        return SimpleNamespace(box_count=box_count, boxes=boxes,
                               triggerbox_name=SimpleNamespace(value=self.string()))

    def entity(self):
        entity_type = self.string()
        entity = None
        if entity_type == "model":
            entity = SimpleNamespace(model_name=SimpleNamespace(value=self.string()),
                                     position=self.v3(), rotation=self.v3(), scale=self.v3())
        elif entity_type == "light":
            entity = SimpleNamespace(position=self.v3(), range=self.f32(),
                                     color=SimpleNamespace(value=self.string()),
                                     intensity=self.f32())
        elif entity_type == "soundemitter":
            entity = SimpleNamespace(position=self.v3(), sound_index=self.u32(),
                                     range=self.f32())
        elif entity_type == "screen":
            entity = SimpleNamespace(position=self.v3(),
                                     screen_texture=SimpleNamespace(value=self.string()))
        elif entity_type == "waypoint":
            entity = SimpleNamespace(position=self.v3())
        elif entity_type == "playerstart":
            entity = SimpleNamespace(position=self.v3(),
                                     angles=SimpleNamespace(value=self.string()))
        elif entity_type == "spotlight":
            entity = SimpleNamespace(position=self.v3(), range=self.f32(),
                                     color=SimpleNamespace(value=self.string()),
                                     intensity=self.f32(),
                                     angles=SimpleNamespace(value=self.string()),
                                     inner_cone_angle=self.i32(),
                                     outter_cone_angle=self.i32())
        else:
            raise RMeshFormatError(
                f"Unsupported entity type {entity_type!r}; cannot safely skip its payload"
            )
        return SimpleNamespace(entity_type=SimpleNamespace(value=entity_type),
                               entity=entity)

    def parse(self):
        room_mesh_type = self.string()
        mesh_count = self.count("Submesh", 1)
        submeshes = [self.submesh() for _ in range(mesh_count)]

        inv_mesh_count = self.count("Invisible submesh", 1)
        inv_submeshes = []
        for _ in range(inv_mesh_count):
            vertex_count = self.count("Invisible mesh vertex", 12)
            vertices = [self.v3() for _ in range(vertex_count)]
            index_count = self.count("Invisible mesh triangle", 12)
            indices = [self.v3i() for _ in range(index_count)]
            inv_submeshes.append(SimpleNamespace(vertex_count=vertex_count,
                                                  vertices=vertices,
                                                  index_count=index_count,
                                                  indices=indices))

        triggerboxes = []
        triggerbox_count = 0
        if room_mesh_type == "RoomMesh.HasTriggerBox":
            triggerbox_count = self.count("Trigger box group", 1)
            triggerboxes = [self.triggerbox() for _ in range(triggerbox_count)]

        point_count = self.count("Entity", 1)
        entities = [self.entity() for _ in range(point_count)]
        eof = self.string()
        if self.remaining:
            raise RMeshFormatError(f"Unexpected {self.remaining} trailing byte(s) after RMesh terminator")

        return SimpleNamespace(
            room_mesh_type=SimpleNamespace(value=room_mesh_type),
            mesh_count=mesh_count, submeshes=submeshes,
            inv_mesh_count=inv_mesh_count, inv_submeshes=inv_submeshes,
            triggerbox_count=triggerbox_count, triggerboxes=triggerboxes,
            point_count=point_count, entities=entities,
            eof=SimpleNamespace(value=eof)
        )


class RoomMesh:
    """Parsed SCP: Containment Breach room mesh."""

    TextureType = TextureType

    @classmethod
    def from_bytes(cls, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("RMesh data must be bytes-like")
        return _Reader(bytes(data)).parse()

    @classmethod
    def from_file(cls, filepath):
        path = Path(filepath)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise RMeshFormatError(f"Cannot read RMesh file {path}: {exc}") from exc
        return cls.from_bytes(data)
