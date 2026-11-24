import struct
import unittest

from room_mesh import RoomMesh, RMeshFormatError


def _string(value):
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _empty_rmesh():
    return b"".join((
        _string("RoomMesh"),
        struct.pack("<I", 0),  # submeshes
        struct.pack("<I", 0),  # invisible submeshes
        struct.pack("<I", 0),  # entities
        _string("EOF"),
    ))


class RoomMeshReaderTests(unittest.TestCase):
    def test_reads_empty_room_mesh(self):
        result = RoomMesh.from_bytes(_empty_rmesh())
        self.assertEqual(result.room_mesh_type.value, "RoomMesh")
        self.assertEqual(result.mesh_count, 0)
        self.assertEqual(result.inv_mesh_count, 0)
        self.assertEqual(result.point_count, 0)
        self.assertEqual(result.eof.value, "EOF")

    def test_rejects_truncated_file(self):
        with self.assertRaises(RMeshFormatError):
            RoomMesh.from_bytes(_empty_rmesh()[:-2])

    def test_rejects_unreasonable_collection_count(self):
        data = _string("RoomMesh") + struct.pack("<I", 0xFFFFFFFF)
        with self.assertRaises(RMeshFormatError):
            RoomMesh.from_bytes(data)

    def test_rejects_invalid_utf8(self):
        data = struct.pack("<I", 1) + b"\xff"
        with self.assertRaises(RMeshFormatError):
            RoomMesh.from_bytes(data)

    def test_rejects_trailing_or_unparsed_data(self):
        with self.assertRaises(RMeshFormatError):
            RoomMesh.from_bytes(_empty_rmesh() + b"extra")


if __name__ == "__main__":
    unittest.main()
