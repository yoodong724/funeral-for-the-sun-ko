extends SceneTree

# This adapter only publishes the final file after the independent serialized
# comparison and a second Godot load succeed. The surrounding project and pack
# must be isolated by the caller; see scene_localize.ko.md.
const VERIFY_SOURCE = """
import hashlib, importlib.util, json, pathlib, sys

def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result

try:
    module_path, module_hash, source_path, candidate_path, plan_path, phase = sys.argv[1:]
    if hashlib.sha256(pathlib.Path(module_path).read_bytes()).hexdigest() != module_hash:
        raise ValueError('inspector hash')
    with open(plan_path, encoding='utf-8') as f:
        plan = json.load(f, object_pairs_hook=pairs)
    spec = importlib.util.spec_from_file_location('scene_localize_inspector', module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if phase == 'request':
        for key in ('pack_path', 'logical_path', 'binary_path', 'output_dir', 'inspector_path', 'python_executable'):
            if any(ord(c) < 32 or ord(c) in (127, 65533) for c in plan[key]):
                raise ValueError('unsupported path character')
    else:
        source = pathlib.Path(source_path).read_bytes()
        if hashlib.sha256(source).hexdigest() != plan['source_sha256']:
            raise ValueError('source hash')
        document = module._parse(source)
        if document.resources[-1].identity != plan['root_id']:
            raise ValueError('root identity')
        resources = {resource.identity: resource for resource in document.resources[:-1]}
        changes = []
        seen = set()
        for item in plan['changes']:
            key = (item['resource_id'], item['property'])
            if key in seen:
                raise ValueError('duplicate location')
            seen.add(key)
            resource = resources[item['resource_id']]
            properties = [p for p in resource.properties if p.name == item['property']]
            if len(properties) != 1 or properties[0].value.tag != 5 or properties[0].value.text != item['original']:
                raise ValueError('source location or value')
            changes.append(module.StringChange(item['resource_id'], item['property'], (), item['original'], item['replacement']))
        if phase == 'after':
            module.compare_rsrc(source, pathlib.Path(candidate_path).read_bytes(), changes=changes)
        elif phase != 'before':
            raise ValueError('phase')
except Exception as exc:
    print('structure rejected:', type(exc).__name__)
    raise SystemExit(1)
"""

var plan: Dictionary
var found: Dictionary = {}
var seen: Dictionary = {}
var walk_error := ""
var current_root: Resource
var current_owner := ""

func fail(reason: String) -> void:
    printerr("SCENE_LOCALIZE_FAILED: ", reason)
    quit(1)

func has_fields(value: Variant, names: Array) -> bool:
    if not value is Dictionary or value.size() != names.size():
        return false
    for name in names:
        if not value.has(name):
            return false
    return true

func res_path(value: Variant) -> bool:
    if typeof(value) != TYPE_STRING or not value.begins_with("res://") or value.contains("\\"):
        return false
    for index in value.length():
        var codepoint = value.unicode_at(index)
        if codepoint < 32 or codepoint == 127 or codepoint == 0xFFFD:
            return false
    var rest: String = value.trim_prefix("res://")
    if rest.is_empty():
        return false
    for part in rest.split("/", true):
        if part.is_empty() or part == "." or part == ".." or part.contains(":"):
            return false
    return true

func local_id(value: Variant) -> bool:
    if typeof(value) != TYPE_STRING or not value.begins_with("local://"):
        return false
    var suffix: String = value.trim_prefix("local://")
    return not suffix.is_empty() and suffix != "." and suffix != ".." and not suffix.contains("/") and not suffix.contains("\\") and not suffix.contains(":")

func sha256(value: Variant) -> bool:
    if typeof(value) != TYPE_STRING or value.length() != 64:
        return false
    for character in value:
        if not character in "0123456789abcdef":
            return false
    return true

func output_parent_safe(path: String) -> bool:
    var parts = path.trim_prefix("res://").split("/")
    var directory = DirAccess.open("res://")
    if directory == null:
        return false
    for index in range(parts.size() - 1):
        if directory.is_link(parts[index]) or directory.change_dir(parts[index]) != OK:
            return false
    return true

func source_path_matches(logical_path: String, binary_path: String) -> bool:
    # Godot can resolve project-level path and translation remaps before it
    # reads a .remap file. This adapter supports only direct files and the
    # canonical exported scene remap, so do not guess through other mappings.
    var path_remaps = ProjectSettings.get_setting("path_remap/remapped_paths", PackedStringArray())
    if not path_remaps is Array and not path_remaps is PackedStringArray:
        return false
    if path_remaps.size() % 2 != 0:
        return false
    for index in range(0, path_remaps.size(), 2):
        if path_remaps[index] == logical_path:
            return false
    var translations = ProjectSettings.get_setting("internationalization/locale/translation_remaps", {})
    if translations is Dictionary:
        if translations.has(logical_path):
            return false
    elif not ((translations is Array or translations is PackedStringArray) and translations.is_empty()):
        return false
    var remap_path := logical_path + ".remap"
    if not FileAccess.file_exists(remap_path):
        return logical_path == binary_path
    # ResourceLoader uses the first path assignment; ConfigFile keeps the
    # last. Reject extra assignments so the two parsers cannot disagree.
    var nonempty: Array[String] = []
    for line in FileAccess.get_file_as_string(remap_path).split("\n"):
        var stripped := line.strip_edges()
        if not stripped.is_empty():
            nonempty.append(stripped)
    if nonempty.size() != 2 or nonempty[0] != "[remap]":
        return false
    var equals := nonempty[1].find("=")
    if equals < 0 or nonempty[1].substr(0, equals).strip_edges() != "path":
        return false
    var config := ConfigFile.new()
    if config.load(remap_path) != OK:
        return false
    var target = config.get_value("remap", "path", null)
    return res_path(target) and target == binary_path

func validate_request(value: Variant) -> bool:
    var fields = ["format", "pack_path", "pack_sha256", "logical_path", "binary_path", "source_sha256", "root_id", "output_dir", "inspector_path", "inspector_sha256", "python_executable", "changes"]
    if not has_fields(value, fields) or value.format != "scene-localize-v1":
        return false
    for key in ["pack_path", "pack_sha256", "logical_path", "binary_path", "source_sha256", "root_id", "output_dir", "inspector_path", "inspector_sha256", "python_executable"]:
        if typeof(value[key]) != TYPE_STRING:
            return false
    if not res_path(value.logical_path) or not res_path(value.binary_path) or not res_path(value.output_dir):
        return false
    if not (value.logical_path.ends_with(".tscn") or value.logical_path.ends_with(".scn")) or not value.binary_path.ends_with(".scn"):
        return false
    if not local_id(value.root_id) or not sha256(value.source_sha256) or not sha256(value.inspector_sha256):
        return false
    if value.pack_path.is_empty():
        if not value.pack_sha256.is_empty():
            return false
    elif not value.pack_path.is_absolute_path() or not sha256(value.pack_sha256):
        return false
    if not value.inspector_path.is_absolute_path() or not value.python_executable.is_absolute_path():
        return false
    if not value.changes is Array or value.changes.is_empty():
        return false
    var unique: Dictionary = {}
    for change in value.changes:
        if not has_fields(change, ["resource_id", "property", "original", "replacement"]):
            return false
        if not local_id(change.resource_id) or change.resource_id == value.root_id:
            return false
        if typeof(change.property) != TYPE_STRING or change.property.is_empty() or typeof(change.original) != TYPE_STRING or typeof(change.replacement) != TYPE_STRING:
            return false
        var key = JSON.stringify([change.resource_id, change.property])
        if unique.has(key):
            return false
        unique[key] = true
    return true

func check_structure(original: String, candidate: String, request: String, phase: String) -> bool:
    var output: Array = []
    var args = PackedStringArray(["-B", "-c", VERIFY_SOURCE, plan.inspector_path, plan.inspector_sha256, original, candidate, request, phase])
    return OS.execute(plan.python_executable, args, output, true) == 0

func walk(value: Variant, depth: int) -> void:
    if not walk_error.is_empty():
        return
    if depth > 100:
        walk_error = "unsupported nesting"
        return
    if value is Resource:
        var object_id = value.get_instance_id()
        if seen.has(object_id):
            return
        seen[object_id] = true
        var identity := ""
        if value == current_root:
            identity = "$root"
        elif value.resource_path.begins_with(current_owner + "::"):
            var suffix: String = value.resource_path.trim_prefix(current_owner + "::")
            identity = "local://" + suffix
            if not local_id(identity) or value.resource_scene_unique_id != suffix:
                walk_error = "internal identity"
                return
        elif not value.resource_path.is_empty():
            return
        else:
            walk_error = "anonymous resource"
            return
        if found.has(identity):
            walk_error = "duplicate resource identity"
            return
        found[identity] = value
        for property in value.get_property_list():
            if property.usage & PROPERTY_USAGE_STORAGE:
                walk(value.get(property.name), depth + 1)
    elif value is Array:
        for item in value:
            walk(item, depth + 1)
    elif value is Dictionary:
        for key in value:
            walk(key, depth + 1)
            walk(value[key], depth + 1)
    elif typeof(value) == TYPE_OBJECT and is_instance_valid(value):
        walk_error = "non-resource object"

func resolve(scene: Resource, owner: String, after: bool) -> bool:
    current_root = scene
    current_owner = owner
    found = {}
    seen = {}
    walk_error = ""
    walk(scene, 0)
    if not walk_error.is_empty():
        return false
    for change in plan.changes:
        if not found.has(change.resource_id):
            return false
        var resource: Resource = found[change.resource_id]
        var count = 0
        var declared_type = -1
        for property in resource.get_property_list():
            if str(property.name) == change.property and property.usage & PROPERTY_USAGE_STORAGE:
                count += 1
                declared_type = property.type
        var expected: String = change.replacement if after else change.original
        var actual = resource.get(change.property)
        if count != 1 or declared_type != TYPE_STRING or typeof(actual) != TYPE_STRING or actual != expected:
            return false
    return true

func register_dependencies(path: String) -> bool:
    var dependencies = ResourceLoader.get_dependencies(path)
    for dep in dependencies:
        var uid_text: String = dep.get_slice("::", 0)
        var dependency_path: String = dep.get_slice("::", 2)
        if uid_text.begins_with("uid://") and not dependency_path.is_empty():
            var uid = ResourceUID.text_to_id(uid_text)
            if uid == ResourceUID.INVALID_ID:
                return false
            if ResourceUID.has_id(uid):
                if ResourceUID.get_id_path(uid) != dependency_path:
                    return false
            else:
                ResourceUID.add_id(uid, dependency_path)
    for dep in dependencies:
        var first: String = dep.get_slice("::", 0)
        var dependency_path: String = dep.get_slice("::", 2)
        if dependency_path.is_empty():
            if first.begins_with("uid://"):
                var uid = ResourceUID.text_to_id(first)
                if uid == ResourceUID.INVALID_ID or not ResourceUID.has_id(uid):
                    return false
                dependency_path = ResourceUID.get_id_path(uid)
            else:
                dependency_path = first
        if dependency_path.is_empty():
            return false
        var dependency = ResourceLoader.load(dependency_path, "", ResourceLoader.CACHE_MODE_REUSE)
        if dependency == null or (dependency is Script and not dependency.can_instantiate()):
            return false
    return true

func supervise(request_path: String) -> void:
    if not res_path(request_path):
        fail("request path")
        return
    var request_text = FileAccess.get_file_as_string(request_path)
    var json := JSON.new()
    if json.parse(request_text) != OK or not validate_request(json.data):
        fail("request")
        return
    var request: Dictionary = json.data
    var output: Array = []
    var script_path: String = get_script().resource_path
    var args = PackedStringArray(["--headless", "--path", ProjectSettings.globalize_path("res://"),
                                  "--script", script_path, "--", "--worker", request_path])
    var result = OS.execute(OS.get_executable_path(), args, output, true)
    var log: String = str(output[0]) if not output.is_empty() else ""
    if result != 0:
        var allowed = ["request path", "request", "verification tool", "output parent", "output exists", "pack hash",
                       "project shadows source", "pack load", "source path", "source hash", "output directory", "request copy",
                       "source copy", "source structure", "dependency load or UID", "source load or target",
                       "root identity", "save", "output reload or target", "output structure", "output hash"]
        for reason in allowed:
            if ("SCENE_LOCALIZE_FAILED: " + reason + "\n") in log:
                fail(reason)
                return
        fail("worker")
        return
    for line in log.split("\n"):
        var trimmed = line.strip_edges()
        if trimmed.begins_with("ERROR:") or trimmed.begins_with("SCRIPT ERROR:") or trimmed.begins_with("WARNING:"):
            fail("engine diagnostic")
            return
    var marker = "SCENE_LOCALIZE_WORKER_READY "
    var saved_hash := ""
    for line in log.split("\n"):
        if line.begins_with(marker):
            saved_hash = line.trim_prefix(marker).strip_edges()
    var candidate: String = request.output_dir + "/candidate.scn"
    var final_output: String = request.output_dir + "/localized.scn"
    if not sha256(saved_hash) or not output_parent_safe(final_output) or FileAccess.file_exists(final_output):
        fail("worker result")
        return
    if FileAccess.get_file_as_string(request.output_dir + "/request.json") != request_text or FileAccess.get_sha256(candidate) != saved_hash:
        fail("worker result")
        return
    if DirAccess.rename_absolute(ProjectSettings.globalize_path(candidate), ProjectSettings.globalize_path(final_output)) != OK:
        fail("output finalize")
        return
    print("SCENE_LOCALIZE_OK count=", request.changes.size(), " sha256=", saved_hash)
    quit(0)

func _initialize() -> void:
    var arguments = OS.get_cmdline_user_args()
    if arguments.size() == 1:
        supervise(arguments[0])
    elif arguments.size() == 2 and arguments[0] == "--worker":
        run_worker(arguments[1])
    else:
        fail("request path")

func run_worker(request_path: String) -> void:
    if not res_path(request_path):
        fail("request path")
        return
    var request_text = FileAccess.get_file_as_string(request_path)
    var json := JSON.new()
    if json.parse(request_text) != OK or not validate_request(json.data):
        fail("request")
        return
    plan = json.data
    if FileAccess.get_sha256(plan.inspector_path) != plan.inspector_sha256 or not FileAccess.file_exists(plan.python_executable):
        fail("verification tool")
        return
    if not check_structure("", "", ProjectSettings.globalize_path(request_path), "request"):
        fail("request")
        return
    if not output_parent_safe(plan.output_dir):
        fail("output parent")
        return
    var output_absolute: String = ProjectSettings.globalize_path(plan.output_dir)
    if DirAccess.dir_exists_absolute(output_absolute) or FileAccess.file_exists(output_absolute):
        fail("output exists")
        return
    if not plan.pack_path.is_empty():
        if FileAccess.get_sha256(plan.pack_path) != plan.pack_sha256:
            fail("pack hash")
            return
        if FileAccess.file_exists(plan.logical_path) or FileAccess.file_exists(plan.binary_path) or FileAccess.file_exists(plan.logical_path + ".remap"):
            fail("project shadows source")
            return
        if not ProjectSettings.load_resource_pack(plan.pack_path, false):
            fail("pack load")
            return
    if not source_path_matches(plan.logical_path, plan.binary_path):
        fail("source path")
        return
    if FileAccess.get_sha256(plan.binary_path) != plan.source_sha256:
        fail("source hash")
        return
    if DirAccess.make_dir_absolute(output_absolute) != OK:
        fail("output directory")
        return
    var original = plan.output_dir + "/original.scn"
    var candidate = plan.output_dir + "/candidate.scn"
    var request_copy = plan.output_dir + "/request.json"
    var request_file = FileAccess.open(request_copy, FileAccess.WRITE)
    if request_file == null:
        fail("request copy")
        return
    request_file.store_string(request_text)
    request_file.close()
    var input_file = FileAccess.open(plan.binary_path, FileAccess.READ)
    var output_file = FileAccess.open(original, FileAccess.WRITE)
    if input_file == null or output_file == null:
        fail("source copy")
        return
    output_file.store_buffer(input_file.get_buffer(input_file.get_length()))
    output_file.close()
    input_file.close()
    var original_absolute: String = ProjectSettings.globalize_path(original)
    var candidate_absolute: String = ProjectSettings.globalize_path(candidate)
    var request_absolute: String = ProjectSettings.globalize_path(request_copy)
    if not check_structure(original_absolute, candidate_absolute, request_absolute, "before"):
        fail("source structure")
        return
    if not register_dependencies(plan.logical_path):
        fail("dependency load or UID")
        return
    var scene = ResourceLoader.load(plan.logical_path, "", ResourceLoader.CACHE_MODE_IGNORE)
    if not scene is PackedScene or not resolve(scene, plan.logical_path, false):
        fail("source load or target")
        return
    var targets = found.duplicate()
    scene.set_path_cache("")
    scene.set_scene_unique_id(plan.root_id.trim_prefix("local://"))
    if not scene.is_built_in() or not scene.resource_path.is_empty() or scene.resource_scene_unique_id != plan.root_id.trim_prefix("local://"):
        fail("root identity")
        return
    for change in plan.changes:
        targets[change.resource_id].set(change.property, change.replacement)
    if ResourceSaver.save(scene, candidate) != OK:
        fail("save")
        return
    var reloaded = ResourceLoader.load(candidate, "", ResourceLoader.CACHE_MODE_IGNORE)
    if not reloaded is PackedScene or not resolve(reloaded, candidate, true):
        fail("output reload or target")
        return
    if not check_structure(original_absolute, candidate_absolute, request_absolute, "after"):
        fail("output structure")
        return
    var saved_hash = FileAccess.get_sha256(candidate)
    if not sha256(saved_hash):
        fail("output hash")
        return
    print("SCENE_LOCALIZE_WORKER_READY ", saved_hash)
    quit(0)
