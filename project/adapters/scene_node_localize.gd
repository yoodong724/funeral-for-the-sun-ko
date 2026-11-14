extends SceneTree

# The Python supervisor mounts the project and PCK read-only and rejects all
# engine diagnostics. This worker reads/writes only its isolated work folder.
func fail(reason: String) -> void:
    printerr("SCENE_NODE_FAILED: ", reason)
    quit(1)

func source_path_matches(logical_path: String, binary_path: String) -> bool:
    var remaps = ProjectSettings.get_setting("path_remap/remapped_paths", PackedStringArray())
    if not remaps is Array and not remaps is PackedStringArray:
        return false
    if remaps.size() % 2 != 0:
        return false
    for i in range(0, remaps.size(), 2):
        if remaps[i] == logical_path:
            return false
    var translations = ProjectSettings.get_setting("internationalization/locale/translation_remaps", {})
    if translations is Dictionary:
        if translations.has(logical_path):
            return false
    elif not ((translations is Array or translations is PackedStringArray) and translations.is_empty()):
        return false
    var path := logical_path + ".remap"
    if not FileAccess.file_exists(path):
        return logical_path == binary_path
    var nonempty: Array[String] = []
    for line in FileAccess.get_file_as_string(path).split("\n"):
        if not line.strip_edges().is_empty():
            nonempty.append(line.strip_edges())
    if nonempty.size() != 2 or nonempty[0] != "[remap]":
        return false
    var equals := nonempty[1].find("=")
    if equals < 0 or nonempty[1].substr(0, equals).strip_edges() != "path":
        return false
    var config := ConfigFile.new()
    return config.load(path) == OK and config.get_value("remap", "path", null) == binary_path

func register_dependencies(path: String) -> Variant:
    var dependencies := ResourceLoader.get_dependencies(path)
    for dep in dependencies:
        var uid_text := dep.get_slice("::", 0)
        var resource_path := dep.get_slice("::", 2)
        if uid_text.begins_with("uid://") and not resource_path.is_empty():
            var uid := ResourceUID.text_to_id(uid_text)
            if uid == ResourceUID.INVALID_ID:
                return null
            if ResourceUID.has_id(uid):
                if ResourceUID.get_id_path(uid) != resource_path:
                    return null
            else:
                ResourceUID.add_id(uid, resource_path)
    return dependencies

func check_units(scene: PackedScene, units: Array, edited: bool) -> bool:
    var state := scene.get_state()
    var found := {}
    for i in range(state.get_node_count()):
        var path := str(state.get_node_path(i)).trim_prefix("./")
        for j in range(state.get_node_property_count(i)):
            var property := str(state.get_node_property_name(i, j))
            for unit in units:
                if path == unit.node_path.trim_prefix("./") and property == unit.property:
                    var key := JSON.stringify([path, property])
                    if found.has(key):
                        return false
                    var value = state.get_node_property_value(i, j)
                    if typeof(value) != TYPE_STRING or value != (unit.replacement if edited else unit.original):
                        return false
                    found[key] = true
    return found.size() == units.size()

func dump_scene(scene: PackedScene) -> Dictionary:
    var bundle = scene.get("_bundled")
    var state := scene.get_state()
    if not bundle is Dictionary or not bundle.get("variants") is Array or not bundle.get("node_paths", []) is Array:
        return {}
    var variants: Array = bundle.variants
    var types: Array = []
    var strings: Array = []
    for value in variants:
        types.append(typeof(value))
        strings.append(value if typeof(value) == TYPE_STRING else null)
    var nodes: Array = []
    for i in range(state.get_node_count()):
        var props: Array = []
        for j in range(state.get_node_property_count(i)):
            var value = state.get_node_property_value(i, j)
            props.append({"name": str(state.get_node_property_name(i, j)), "type": typeof(value),
                          "string": value if typeof(value) == TYPE_STRING else null})
        nodes.append({"index": i, "path": str(state.get_node_path(i)), "properties": props})
    return {"bundle_version": bundle.get("version", 1), "names": Array(bundle.get("names", PackedStringArray())),
            "node_count": bundle.get("node_count", -1), "nodes": Array(bundle.get("nodes", PackedInt32Array())),
            "connection_count": bundle.get("conn_count", -1), "connections": Array(bundle.get("conns", PackedInt32Array())),
            "node_paths_count": bundle.get("node_paths", []).size(),
            "base_scene": bundle.get("base_scene", -1), "variant_types": types, "variant_strings": strings,
            "state_nodes": nodes}

func _initialize() -> void:
    var arguments := OS.get_cmdline_user_args()
    if arguments.size() != 1 or arguments[0] not in ["inspect", "build", "reload"]:
        fail("mode")
        return
    var config = JSON.parse_string(FileAccess.get_file_as_string("/work/config.json"))
    if not config is Dictionary:
        fail("config")
        return
    if FileAccess.file_exists(config.logical_path) or FileAccess.file_exists(config.binary_path) or FileAccess.file_exists(config.logical_path + ".remap"):
        fail("project shadows source")
        return
    if not ProjectSettings.load_resource_pack("/source/original.pck", false):
        fail("pack load")
        return
    if not source_path_matches(config.logical_path, config.binary_path):
        fail("source path")
        return
    if FileAccess.get_sha256(config.binary_path) != config.source_sha256:
        fail("source hash")
        return
    var dependencies = register_dependencies(config.logical_path)
    if dependencies == null:
        fail("uid conflict")
        return
    var scene = ResourceLoader.load(config.logical_path, "", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
    if not scene is PackedScene:
        fail("source load")
        return
    if arguments[0] == "inspect":
        var state := dump_scene(scene)
        if state.is_empty():
            fail("bundle")
            return
        var output := FileAccess.open("/work/inspection.json", FileAccess.WRITE)
        if output == null:
            fail("inspection output")
            return
        output.store_string(JSON.stringify({"scene": state, "dependencies": Array(dependencies)}))
        output.close()
        quit(0)
        return
    if not check_units(scene, config.changes, false):
        fail("source locations")
        return
    if arguments[0] == "build":
        var bundle: Dictionary = scene.get("_bundled")
        var variants: Array = bundle.get("variants", [])
        var seen := {}
        for edit in config.edits:
            var index: int = edit.variant_index
            if index < 0 or index >= variants.size() or seen.has(index) or typeof(variants[index]) != TYPE_STRING or variants[index] != edit.original:
                fail("variant location")
                return
            seen[index] = true
            variants[index] = edit.replacement
        bundle["variants"] = variants
        scene.set("_bundled", bundle)
        if not check_units(scene, config.changes, true):
            fail("modified locations")
            return
        scene.set_path_cache("")
        scene.set_scene_unique_id(config.root_id.trim_prefix("local://"))
        if not scene.is_built_in() or not scene.resource_path.is_empty() or scene.resource_scene_unique_id != config.root_id.trim_prefix("local://"):
            fail("root identity")
            return
        if ResourceSaver.save(scene, "/work/candidate.scn") != OK:
            fail("save")
            return
        quit(0)
        return
    var candidate = ResourceLoader.load("/work/candidate.scn", "", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
    if not candidate is PackedScene or not check_units(candidate, config.changes, true):
        fail("candidate reload")
        return
    if dependencies != ResourceLoader.get_dependencies("/work/candidate.scn"):
        fail("dependency change")
        return
    quit(0)
