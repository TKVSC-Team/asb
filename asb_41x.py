"""ASB reader for Nintendo Switch Online Playtest versions 0x41A and 0x41B."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from exb import EXB
from utils import ReadStream

from asb import (
    ASB,
    Mode,
    StateCheckType,
    load_s3_enums,
)

PLAYTEST_VERSIONS = frozenset({0x41A, 0x41B})

ELEMENT_TYPE_NAMES = {
    1: "FloatSelector",
    2: "StringSelector",
    3: "SkeletalAnimation",
    4: "State",
    5: "StateEnd",
    6: "OneDimensionalBlender",
    7: "Sequential",
    8: "IntSelector",
    9: "Simultaneous",
    10: "Event",
    11: "MaterialAnimation",
    12: "FrameController",
    13: "DummyAnimation",
    14: "RandomSelector",
    15: "StateEnd",
    16: "PreviousTagSelector",
    17: "BonePositionSelector",
    18: "BoneAnimation",
    19: "InitialFrame",
    20: "BoneBlender",
    21: "BoolSelector",
    22: "Alert",
    23: "SubtractAnimation",
    24: "ShapeAnimation",
    25: "Unknown7",
    26: "TwoDimensionalBlender",
    27: "Unknown7",
}


@dataclass
class Header41x:
    name_off: int
    command_count: int
    command_array: int
    element_count: int
    element_array: int
    event_count: int
    event_array: int
    partial_count: int
    partial_array: int
    attachment_count: int
    attachment_array: int
    attachment_index_array: int
    blackboard: int
    string_pool: int
    enum_array: int
    state_array: int
    float_property_ex_count: int
    float_property_ex_array: int
    bone_blend_count: int
    bone_blend_array: int
    partial_skeleton_count: int
    partial_skeleton_array: int
    string_pool_size: int
    transition_array: int
    transition_partial_skeleton_array: int
    tag_array: int
    external_action_array: int
    exb: int
    transition_group_array: int
    material_blend_array: int


def _guid_str(data: bytes, offset: int) -> str:
    a = struct.unpack_from("<I", data, offset)[0]
    b, c = struct.unpack_from("<HH", data, offset + 4)
    d = data[offset + 8 : offset + 16]
    return "%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x" % (
        a,
        b,
        c,
        d[0],
        d[1],
        d[2],
        d[3],
        d[4],
        d[5],
        d[6],
        d[7],
    )


def _read_header(data: bytes) -> Header41x:
    return Header41x(
        name_off=struct.unpack_from("<I", data, 0x8)[0],
        command_count=struct.unpack_from("<I", data, 0xC)[0],
        command_array=struct.unpack_from("<I", data, 0x10)[0],
        element_count=struct.unpack_from("<I", data, 0x14)[0],
        element_array=struct.unpack_from("<I", data, 0x18)[0],
        event_count=struct.unpack_from("<I", data, 0x1C)[0],
        event_array=struct.unpack_from("<I", data, 0x20)[0],
        partial_count=struct.unpack_from("<I", data, 0x24)[0],
        partial_array=struct.unpack_from("<I", data, 0x28)[0],
        attachment_count=struct.unpack_from("<I", data, 0x2C)[0],
        attachment_array=struct.unpack_from("<I", data, 0x30)[0],
        attachment_index_array=struct.unpack_from("<I", data, 0x34)[0],
        blackboard=struct.unpack_from("<I", data, 0x38)[0],
        string_pool=struct.unpack_from("<I", data, 0x3C)[0],
        enum_array=struct.unpack_from("<I", data, 0x40)[0],
        state_array=struct.unpack_from("<I", data, 0x44)[0],
        float_property_ex_count=struct.unpack_from("<I", data, 0x4C)[0],
        float_property_ex_array=struct.unpack_from("<I", data, 0x48)[0],
        bone_blend_count=struct.unpack_from("<I", data, 0x50)[0],
        bone_blend_array=struct.unpack_from("<I", data, 0x54)[0],
        partial_skeleton_count=struct.unpack_from("<I", data, 0x58)[0],
        partial_skeleton_array=struct.unpack_from("<I", data, 0x5C)[0],
        string_pool_size=struct.unpack_from("<I", data, 0x60)[0],
        transition_array=struct.unpack_from("<I", data, 0x64)[0],
        transition_partial_skeleton_array=struct.unpack_from("<I", data, 0x68)[0],
        tag_array=struct.unpack_from("<I", data, 0x6C)[0],
        external_action_array=struct.unpack_from("<I", data, 0x70)[0],
        exb=struct.unpack_from("<I", data, 0x74)[0],
        transition_group_array=struct.unpack_from("<I", data, 0x78)[0],
        material_blend_array=struct.unpack_from("<I", data, 0x7C)[0],
    )


def _read_asb_array_count(data: bytes, offset: int) -> int:
    if offset == 0:
        return 0
    return struct.unpack_from("<I", data, offset)[0]


def _read_tag_array(data: bytes, offset: int, pool: ReadStream) -> list[str]:
    count = _read_asb_array_count(data, offset)
    if count == 0:
        return []
    tags = []
    base = offset + 4
    for i in range(count):
        tags.append(pool.read_string(struct.unpack_from("<I", data, base + i * 4)[0]))
    return tags


class Asb41xBodyReader(ASB):
    """Reuse legacy ASB node body parsers against 0x41x element param streams."""

    def __init__(self, data: bytes, pool: ReadStream, version: int):
        super().__init__(None, ReadStream(data), pool)
        self.version = version
        self._file = data
        self.nodes = []
        self.state_transitions = []
        self.material_blend = []
        self.as_markings = []
        self.events = []
        self.calc_ctrl = []

    def read_plugs(self):
        offsets = {
            "State": [],
            "Unk": [],
            "Child": [],
            "State Transition": [],
            "Event": [],
            "Frame Controls": [],
        }
        state_count = self.stream.read_u8()
        state_index = self.stream.read_u8()
        unknown_count = self.stream.read_u8()
        unknown_index = self.stream.read_u8()
        child_count = self.stream.read_u8()
        child_index = self.stream.read_u8()
        exb_count = self.stream.read_u8()
        exb_index = self.stream.read_u8()
        event_count = self.stream.read_u8()
        event_index = self.stream.read_u8()
        frame_count = self.stream.read_u8()
        frame_index = self.stream.read_u8()
        plug_base = self.stream.tell()
        plug_offsets = []
        total = (
            state_count
            + unknown_count
            + child_count
            + exb_count
            + event_count
            + frame_count
        )
        for _ in range(total):
            plug_offsets.append(self.stream.read_u32())
        for i in range(state_count):
            offsets["State"].append(plug_base + plug_offsets[state_index + i])
        for i in range(unknown_count):
            offsets["Unk"].append(plug_base + plug_offsets[unknown_index + i])
        for i in range(child_count):
            offsets["Child"].append(plug_base + plug_offsets[child_index + i])
        for i in range(exb_count):
            offsets["State Transition"].append(plug_base + plug_offsets[exb_index + i])
        for i in range(event_count):
            offsets["Event"].append(plug_base + plug_offsets[event_index + i])
        for i in range(frame_count):
            offsets["Frame Controls"].append(plug_base + plug_offsets[frame_index + i])

        state = []
        if offsets["State"]:
            for offset in offsets["State"]:
                self.stream.seek(offset)
                state.append(self.stream.read_u32())
        transition = []
        if offsets["State Transition"]:
            for offset in offsets["State Transition"]:
                self.stream.seek(offset)
                index = self.stream.read_s32()
                entry = {"State Transition": {}, "Node Index": -1}
                if index >= 0:
                    entry["State Transition"] = self.state_transitions[index]
                transition.append(entry)
        event = []
        if offsets["Event"]:
            for offset in offsets["Event"]:
                self.stream.seek(offset)
                event.append(self.stream.read_u32())
        frame = []
        if offsets["Frame Controls"]:
            for offset in offsets["Frame Controls"]:
                self.stream.seek(offset)
                frame.append(self.stream.read_u32())
        return offsets, transition, event, frame, state

    def read_connections(self):
        return self.read_plugs()

    def read_element_body(self, node_type: str, param_offset: int):
        if param_offset == 0 or node_type == "StateEnd":
            return {}
        self.stream.seek(param_offset)
        method = getattr(self, node_type, None)
        if method is None:
            return {}
        return method()


class Blackboard41x:
    TYPE_ORDER = ["string", "int", "uint", "float", "bool", "vec3f"]

    def __init__(self, data: bytes, offset: int, pool: ReadStream):
        self.stream = ReadStream(data)
        self.string_pool = pool
        self.stream.seek(offset)
        self.blackboard = {}
        headers = [self._read_header() for _ in self.TYPE_ORDER]
        entry_base = offset + len(self.TYPE_ORDER) * 8
        entry_pos = entry_base
        typed_entries = {}
        for type_name, header in zip(self.TYPE_ORDER, headers):
            typed_entries[type_name] = []
            self.stream.seek(entry_pos)
            for _ in range(header["Count"]):
                typed_entries[type_name].append(self._read_entry())
            entry_pos += header["Count"] * 4
        value_base = entry_pos
        for type_name, header in zip(self.TYPE_ORDER, headers):
            if header["Count"] == 0:
                continue
            self.stream.seek(value_base + header["Value Offset"])
            self.blackboard[type_name] = []
            for entry in typed_entries[type_name]:
                entry["Init Value"] = self._read_value(type_name)
                self.blackboard[type_name].append(entry)
        self.blackboard = {k: v for k, v in self.blackboard.items() if v}

    def _read_header(self):
        return {
            "Count": self.stream.read_u16(),
            "Index": self.stream.read_u16(),
            "Value Offset": self.stream.read_u16(),
            "Reserved": self.stream.read_u16(),
        }

    def _read_entry(self):
        entry = {}
        flags = self.stream.read_u32()
        valid_index = bool(flags >> 31)
        if valid_index:
            entry["Index"] = (flags >> 24) & 0x7F
        name_offset = flags & 0xFFFFFF
        entry["Name"] = self.string_pool.read_string(name_offset)
        return entry

    def _read_value(self, datatype):
        if datatype in ("int", "uint", "bool"):
            value = self.stream.read_u32()
            if datatype == "bool":
                value = bool(value)
        elif datatype == "float":
            value = self.stream.read_f32()
        elif datatype == "string":
            value = self.string_pool.read_string(self.stream.read_u32())
        elif datatype == "vec3f":
            value = [self.stream.read_f32(), self.stream.read_f32(), self.stream.read_f32()]
        elif datatype == "ptr":
            value = None
        else:
            value = None
        return value


def _read_enum_reloc(data: bytes, offset: int, pool: ReadStream) -> list[dict]:
    count = _read_asb_array_count(data, offset)
    if count == 0:
        return []
    entries = []
    base = offset + 4
    for i in range(count):
        entry_off = base + i * 12
        patch = struct.unpack_from("<I", data, entry_off)[0]
        class_name = pool.read_string(struct.unpack_from("<I", data, entry_off + 4)[0])
        value_name = pool.read_string(struct.unpack_from("<I", data, entry_off + 8)[0])
        new_value = struct.unpack_from("<I", data, patch)[0]
        entries.append(
            {
                "Patch Offset": patch,
                "Class Name": class_name,
                "Value Name": value_name,
                "New Value": new_value,
            }
        )
    return entries


def _read_material_blend(data: bytes, offset: int, pool: ReadStream) -> list[dict]:
    count = _read_asb_array_count(data, offset)
    if count == 0:
        return []
    blends = []
    base = offset + 4
    for i in range(count):
        entry_off = base + i * 8
        name = pool.read_string(struct.unpack_from("<I", data, entry_off)[0])
        weight = struct.unpack_from("<f", data, entry_off + 4)[0]
        blends.append({"Name": name, "Blend Start": weight})
    return blends


def _read_partial_skeletons(data: bytes, offset: int, count: int, pool: ReadStream) -> list[dict]:
    groups = []
    for i in range(count):
        entry_off = offset + i * 0x10
        bone_array = struct.unpack_from("<I", data, entry_off)[0]
        name = pool.read_string(struct.unpack_from("<I", data, entry_off + 4)[0])
        bone_count = struct.unpack_from("<I", data, entry_off + 8)[0]
        bones = []
        if bone_array and bone_count:
            bone_base = bone_array + 4
            for j in range(bone_count):
                bone_off = bone_base + j * 8
                if bone_off + 8 > len(data):
                    break
                bone_name = pool.read_string(struct.unpack_from("<I", data, bone_off)[0])
                flags = struct.unpack_from("<h", data, bone_off + 4)[0]
                bones.append({"Name": bone_name, "Unknown 1": flags & 0xFF, "Unknown 2": (flags >> 8) & 0xFF})
        groups.append({"Name": name, "Bones": bones})
    return groups


def _read_partials(data: bytes, offset: int, count: int, pool: ReadStream) -> list[dict]:
    partials = []
    for i in range(count):
        entry_off = offset + i * 0x10
        name = pool.read_string(struct.unpack_from("<I", data, entry_off)[0])
        skel_id = struct.unpack_from("<I", data, entry_off + 4)[0]
        unknown = pool.read_string(struct.unpack_from("<I", data, entry_off + 8)[0])
        partials.append({"Name": name, "Unknown": unknown, "Skeleton Id": skel_id})
    return partials


def _read_commands(data: bytes, header: Header41x, pool: ReadStream) -> list[dict]:
    commands = []
    for i in range(header.command_count):
        off = header.command_array + i * 0x30
        command = {}
        command["Name"] = pool.read_string(struct.unpack_from("<I", data, off)[0])
        tag_ptr = struct.unpack_from("<I", data, off + 4)[0]
        if tag_ptr:
            command["Tags"] = _read_tag_array(data, tag_ptr, pool)
        body = Asb41xBodyReader(data, pool, struct.unpack_from("<I", data, 4)[0])
        body.stream.seek(off + 8)
        command["Unknown 1"] = body.parse_param("float")
        body.stream.read_u32()  # debug flag
        command["Ignore Same Command"] = body.parse_param("bool")
        command["Interpolation Type"] = body.stream.read_u32()
        command["GUID"] = _guid_str(data, off + 0x1C)
        command["Node Index"] = struct.unpack_from("<H", data, off + 0x2C)[0]
        commands.append(command)
    return commands


def _read_states(data: bytes, offset: int) -> list[dict]:
    count = _read_asb_array_count(data, offset)
    if count == 0:
        return []
    states = []
    base = offset + 4
    for i in range(count):
        entry_off = base + i * 0x60
        state = {
            "Current Node": struct.unpack_from("<H", data, entry_off)[0],
            "Target Node": struct.unpack_from("<H", data, entry_off + 2)[0],
            "Check Type": StateCheckType(struct.unpack_from("<I", data, entry_off + 4)[0]).name,
        }
        states.append(state)
    return states


def _read_float_property_ex(data: bytes, offset: int, count: int, body: Asb41xBodyReader) -> list[dict]:
    controllers = []
    for i in range(count):
        entry_off = offset + i * 0x20
        body.stream.seek(entry_off)
        controller = {}
        index = body.stream.read_s32()
        if index < 0:
            controller["Parameter"] = {"Command Data Type": index & 0xFFFF}
        else:
            controller["Parameter"] = {"Blackboard Index": index & 0xFFFF, "Type": "float"}
        controller["Adjust Value"] = body.stream.read_f32()
        controller["Calc Mode"] = Mode(body.stream.read_u32()).name
        controller["Default Value"] = body.stream.read_f32()
        controller["Adjust Rate"] = body.stream.read_f32()
        controller["Base Result"] = body.stream.read_f32()
        controller["Min"] = body.stream.read_f32()
        controller["Max"] = body.stream.read_f32()
        controllers.append(controller)
    return controllers


def _read_elements(
    data: bytes,
    header: Header41x,
    pool: ReadStream,
    body: Asb41xBodyReader,
    attachments: list,
    attachment_indices: list[int],
) -> list[dict]:
    nodes = []
    for i in range(header.element_count):
        off = header.element_array + i * 0x24
        element_type = struct.unpack_from("<H", data, off)[0]
        attach_count = data[off + 2]
        no_state_end = bool(data[off + 3])
        tag_ptr = struct.unpack_from("<I", data, off + 4)[0]
        param_ptr = struct.unpack_from("<I", data, off + 8)[0]
        node_type = ELEMENT_TYPE_NAMES.get(element_type, f"Unknown{element_type}")
        fpex_flags = struct.unpack_from("<H", data, off + 0xC)[0]
        fpex_count = struct.unpack_from("<H", data, off + 0xE)[0]
        attach_base = struct.unpack_from("<H", data, off + 0x10)[0]
        node = {
            "Node Index": i,
            "Node Type": node_type,
            "No State Transition": no_state_end,
            "GUID": _guid_str(data, off + 0x14),
        }
        if tag_ptr:
            node["Tags"] = _read_tag_array(data, tag_ptr, pool)
        if fpex_count > 0:
            node["Calc Controllers"] = body.calc_ctrl[fpex_flags : fpex_flags + fpex_count]
        if attach_count > 0:
            node["Sync Controls"] = []
            for j in range(attach_count):
                attach_id = attachment_indices[attach_base + j]
                if attach_id < len(attachments):
                    node["Sync Controls"].append(attachments[attach_id])
        if node_type not in ("StateEnd",):
            body.stream.seek(0)
            try:
                node["Body"] = body.read_element_body(node_type, param_ptr)
            except Exception:
                node["Body"] = {}
        nodes.append(node)
    return nodes


def _read_attachments(data: bytes, offset: int, count: int) -> list[dict]:
    attachments = []
    for i in range(count):
        entry_off = offset + i * 0x18
        attach_type = struct.unpack_from("<H", data, entry_off)[0]
        data_ptr = struct.unpack_from("<I", data, entry_off + 4)[0]
        guid = _guid_str(data, entry_off + 8)
        attachments.append({"Type": attach_type, "Data Offset": data_ptr, "GUID": guid})
    return attachments


def _read_attachment_indices(data: bytes, offset: int, count: int) -> list[int]:
    return list(struct.unpack_from(f"<{count}I", data, offset))


def from_binary_41x(data: bytes | bytearray) -> ASB:
    if not ASB._ENUM_DB:
        load_s3_enums()
    assert data[:4] == b"ASB "
    version = struct.unpack_from("<I", data, 4)[0]
    header = _read_header(data)
    pool_bytes = data[header.string_pool : header.string_pool + header.string_pool_size]
    pool = ReadStream(pool_bytes)

    asb = ASB(None)
    asb.version = version
    asb.filename = pool.read_string(header.name_off)
    asb.has_asnode_baev = False
    asb.enum_resolve = _read_enum_reloc(data, header.enum_array, pool)
    for entry in asb.enum_resolve:
        value = ASB._search_enum_db(entry["Class Name"], entry["Value Name"])
        if value is not None:
            entry["New Value"] = value
            struct.pack_into("<i", data, entry["Patch Offset"], value)

    asb.blackboard = Blackboard41x(data, header.blackboard, pool).blackboard
    asb.material_blend = _read_material_blend(data, header.material_blend_array, pool)
    asb.bone_groups = _read_partial_skeletons(
        data, header.partial_skeleton_array, header.partial_skeleton_count, pool
    )
    asb.partials = _read_partials(data, header.partial_array, header.partial_count, pool)
    asb.state_transitions = _read_states(data, header.state_array)

    body = Asb41xBodyReader(data, pool, version)
    body.state_transitions = asb.state_transitions
    body.material_blend = asb.material_blend
    body.calc_ctrl = _read_float_property_ex(
        data, header.float_property_ex_array, header.float_property_ex_count, body
    )
    asb.calc_ctrl = body.calc_ctrl

    attachments = _read_attachments(data, header.attachment_array, header.attachment_count)
    attachment_indices = _read_attachment_indices(
        data, header.attachment_index_array, header.attachment_count
    )

    asb.commands = _read_commands(data, header, pool)
    asb.nodes = _read_elements(data, header, pool, body, attachments, attachment_indices)
    asb.valid_tags = _read_tag_array(data, header.tag_array, pool)

    if header.exb:
        try:
            asb.expressions = EXB(data[header.exb:]).exb_section
        except Exception:
            asb.expressions = []
    else:
        asb.expressions = []

    asb.transitions = []
    asb.events = []
    asb.sync_ctrl = attachments
    asb.as_markings = []
    asb.command_groups = []
    return asb
