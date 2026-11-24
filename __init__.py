bl_info = {
    "name": "RMesh Importer",
    "description": "Imports SCP: Containment Breach RMesh files",
    "author": "señorDane, MSTendo64",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "File > Import > RMESH",
    "category": "Import",
}

import bpy
import bmesh
import mathutils
import os
from pathlib import Path
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from bpy_extras import object_utils

if "room_mesh" in locals():
    import importlib
    importlib.reload(room_mesh)
else:
    from . import room_mesh


def _new_empty(context, name, parent=None):
    obj = bpy.data.objects.new(name, None)
    context.collection.objects.link(obj)
    obj.parent = parent
    return obj


def _find_texture_file(texture_name, texture_dir):
    """Resolve a texture path, including game-relative names beside the RMesh."""
    texture_dir = Path(texture_dir)
    raw_path = Path(texture_name)

    candidates = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(texture_dir / raw_path)
        # RMesh texture names may contain game-internal directories. If the
        # texture was exported beside the room, try its basename as well.
        if raw_path.name != str(raw_path):
            candidates.append(texture_dir / raw_path.name)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    # Some RMesh texture references omit the image extension.
    bases = []
    for candidate in candidates:
        bases.append(candidate)
        if not candidate.suffix:
            for extension in (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds"):
                bases.append(candidate.with_suffix(extension))

    for candidate in bases:
        if candidate.is_file():
            return candidate

    # Case-insensitive fallback for assets copied from case-sensitive game
    # archives onto Windows or other filesystems.
    wanted_names = {candidate.name.casefold() for candidate in bases}
    try:
        for entry in texture_dir.iterdir():
            if entry.is_file() and entry.name.casefold() in wanted_names:
                return entry
    except OSError:
        pass

    return None


def _material_for_texture(texture_name, texture_dir, materials, load_images, operator):
    texture_path = Path(texture_name)
    material_name = texture_path.stem or "RMesh_Material"

    if material_name in materials:
        return materials[material_name]

    material = bpy.data.materials.new(name=material_name)
    material.use_nodes = True
    materials[material_name] = material

    if not load_images:
        return material

    image_path = _find_texture_file(texture_name, texture_dir)
    if image_path is None:
        operator.report(
            {'WARNING'},
            f"Texture not found beside RMesh or at referenced path: {texture_name}"
        )
        return material

    try:
        image = bpy.data.images.load(str(image_path), check_existing=True)
    except (RuntimeError, OSError) as exc:
        operator.report({'WARNING'}, f"Could not load texture {image_path}: {exc}")
        return material

    nodes = material.node_tree.nodes
    principled = nodes.get("Principled BSDF")
    if principled is None:
        principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    output = nodes.get("Material Output")
    if output is None:
        output = nodes.new(type="ShaderNodeOutputMaterial")

    links = material.node_tree.links
    if not any(link.from_node == principled and link.to_node == output
               for link in links):
        links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    image_node = nodes.new(type="ShaderNodeTexImage")
    image_node.image = image
    links.new(image_node.outputs["Color"], principled.inputs["Base Color"])
    return material


class ImportRMeshOperator(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.rmesh"
    bl_label = "RMesh (.rmesh)"
    bl_options = {'UNDO'}

    filename_ext = ".rmesh"
    filter_glob: StringProperty(default="*.rmesh", options={'HIDDEN'})
    use_imp_mats: BoolProperty(name="Import Materials", default=True)
    use_ents: BoolProperty(name="Import Entities as empties", default=True)
    import_scale: bpy.props.FloatProperty(
        name="Import Scale",
        description="Scale factor for SCP: Containment Breach world coordinates",
        default=0.00625, min=0.000001, max=1.0,
        precision=6,
    )

    def execute(self, context):
        filepath = Path(self.filepath)
        try:
            rmesh = room_mesh.RoomMesh.from_file(filepath)
        except (room_mesh.RMeshFormatError, OSError, ValueError) as exc:
            self.report({'ERROR'}, f"Could not import RMesh: {exc}")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"RMesh: {rmesh.mesh_count} submeshes, {rmesh.point_count} entities"
        )

        root = _new_empty(context, filepath.stem)
        mesh_parent = _new_empty(context, "meshes", root) if self.use_ents else root
        materials = {}

        for submesh_index, submesh in enumerate(rmesh.submeshes):
            # The second texture slot is the surface texture in the source format.
            texture_name = submesh.textures[1].texture_name.value
            material_name = Path(texture_name).stem or f"submesh_{submesh_index}"
            mesh = bpy.data.meshes.new(f"sm{submesh_index}_{material_name}")
            bm = bmesh.new()
            uv1 = bm.loops.layers.uv.new("uv1")
            uv2 = bm.loops.layers.uv.new("uv2")

            try:
                for vertex in submesh.vertices:
                    position = vertex.position
                    bm.verts.new((position.x * self.import_scale, position.z * self.import_scale, position.y * self.import_scale))
                bm.verts.ensure_lookup_table()
                bm.verts.index_update()

                for triangle_index, indices in enumerate(submesh.indices):
                    triangle = (indices.z, indices.y, indices.x)
                    if any(index >= len(bm.verts) for index in triangle):
                        self.report(
                            {'WARNING'},
                            f"Submesh {submesh_index}: skipped out-of-range triangle {triangle_index}"
                        )
                        continue
                    try:
                        face = bm.faces.new([bm.verts[index] for index in triangle])
                    except ValueError:
                        # Duplicate/degenerate face; skip only this face.
                        continue

                    for loop in face.loops:
                        vertex = submesh.vertices[loop.vert.index]
                        loop[uv1].uv = (vertex.uv1.x, 1.0 - vertex.uv1.y)
                        loop[uv2].uv = (vertex.uv2.x, 1.0 - vertex.uv2.y)

                bm.to_mesh(mesh)
            finally:
                bm.free()

            mesh.update()
            obj = bpy.data.objects.new(mesh.name, mesh)
            context.collection.objects.link(obj)
            obj.parent = mesh_parent

            if self.use_imp_mats:
                material = _material_for_texture(
                    texture_name, filepath.parent, materials, True, self
                )
                obj.data.materials.append(material)

        if self.use_ents:
            entity_parent = _new_empty(context, "entities", root)
            for index, point in enumerate(rmesh.entities):
                entity_type = point.entity_type.value
                entity_data = point.entity
                name = f"{index}_{entity_type}"
                if entity_type == "model":
                    name += "_" + entity_data.model_name.value

                entity_obj = _new_empty(context, name, entity_parent)
                position = getattr(entity_data, "position", None)
                if position is not None:
                    entity_obj.location = (position.x * self.import_scale, position.z * self.import_scale, position.y * self.import_scale)

                if entity_type in {"light", "spotlight", "soundemitter"} and hasattr(entity_data, "range"):
                    entity_obj["source_range"] = entity_data.range
                    entity_obj["range"] = entity_data.range * self.import_scale
                if entity_type == "model":
                    rotation = entity_data.rotation
                    scale = entity_data.scale
                    entity_obj.rotation_euler = (rotation.x, rotation.z, rotation.y)
                    entity_obj.scale = (scale.x, scale.z, scale.y)

        return {'FINISHED'}


class ImportRMeshPanel(bpy.types.Panel):
    bl_label = "RMesh Import"
    bl_idname = "PT_RMeshImporter"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'UI'
    bl_category = 'Import'

    def draw(self, context):
        self.layout.operator(ImportRMeshOperator.bl_idname)


def menu_func_import(self, context):
    self.layout.operator(ImportRMeshOperator.bl_idname, text="RMesh (.rmesh)")


_CLASSES = (ImportRMeshOperator, ImportRMeshPanel)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
