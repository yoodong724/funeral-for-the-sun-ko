#!/usr/bin/env python3
"""Verify the approved 072 map pixel scope; classify replacement fonts as unsupported.

The four-entry policy and map approval are intentionally specific. This is not a
font safety, licensing, full PCK, or game behavior verifier.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from project.adapters import funeral, script_localize

MAP = '.godot/imported/mapfin.png-30a72a6618e56d0d6eab4bbad3142439.ctex'
FONTS = (
    '.godot/imported/Cinzel-Bold.ttf-4dbe34d004a4913050405fb2923d7611.fontdata',
    '.godot/imported/georgia.ttf-5c2472956060af693a988d4708ff8b11.fontdata',
    '.godot/imported/Caveat-VariableFont_wght.ttf-ebd5db441f218addc2355fb974d637cc.fontdata',
)
MAP_OLD = '511f8f8ac241f076cd359a57fefa23da4d62fff92522a45da3c5af6d27edf123'
MAP_APPROVED = 'a50504cc8b01a0e0ba2914dc6543e2fec03102e19a24496f04f969fa761fe35f'
FONT_APPROVED = 'c81863fef67dc5c5c8deebf6f3c855917d0ac7d2c8bbbb6540c4befb5b2a1e49'
GODOT_SHA = '54215149d52efb1d653a3dec39d0993587bdf5daa2c56e787b5ee88417fb1339'
MAP_SIZE = (1587, 941)
MAP_RECT = (150, 820, 270, 865)  # Existing independently reviewed permissible box.
CTEX_HEADER = bytes.fromhex(
    '475354320100000033060000ad0300000000000dffffffff0000000000000000'
    '00000000020000003306ad030000000005000000'
)
MAX_ENTRY = 64 * 1024 * 1024


class VerificationError(ValueError):
    pass


class UnsupportedFormat(VerificationError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def read_plan(path):
    raw = Path(path).read_bytes()
    try:
        spec = json.loads(raw.decode('utf-8'), object_pairs_hook=script_localize.object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, script_localize.LocalizeError) as exc:
        raise VerificationError('invalid plan JSON') from exc
    if not isinstance(spec, dict) or set(spec) != {'format', 'original_pck_sha256', 'final_pck_sha256', 'assets'}:
        raise VerificationError('invalid plan fields')
    if spec['format'] != 'funeral-asset-scope-072-v1':
        raise VerificationError('unsupported plan format')
    for key in ('original_pck_sha256', 'final_pck_sha256'):
        if not isinstance(spec[key], str) or not re.fullmatch('[0-9a-f]{64}', spec[key]):
            raise VerificationError('invalid PCK digest')
    expected = [{'entry': MAP, 'kind': 'approved-map'}, *({'entry': f, 'kind': 'fontdata'} for f in FONTS)]
    if spec['assets'] != expected:
        raise VerificationError('asset scope differs from approved four entries')
    return raw, spec


def _entry(pack, index, name):
    if name not in index.entries:
        raise VerificationError('missing PCK entry: ' + name)
    entry = index.entries[name]
    if entry.size <= 0 or entry.size > MAX_ENTRY:
        raise UnsupportedFormat('entry size outside supported range')
    with Path(pack).open('rb') as stream:
        stream.seek(entry.offset)
        data = stream.read(entry.size)
    if len(data) != entry.size or hashlib.md5(data).digest() != entry.md5:
        raise VerificationError('PCK entry truncated or checksum mismatch: ' + name)
    return data


def compare_rgba(old, new, width, height, rect):
    """Reject alpha changes anywhere and any RGBA changes outside rect."""
    if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0 or
            len(old) != width * height * 4 or len(new) != len(old)):
        raise VerificationError('invalid RGBA dimensions or data')
    if not isinstance(rect, (tuple, list)) or len(rect) != 4 or any(type(v) is not int for v in rect):
        raise VerificationError('invalid allowed rectangle')
    x0, y0, x1, y1 = rect
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise VerificationError('rectangle outside image')
    changes = 0
    for y in range(height):
        for x in range(width):
            i = 4 * (y * width + x)
            if old[i + 3] != new[i + 3]:
                raise VerificationError('alpha changed')
            if old[i:i + 4] != new[i:i + 4]:
                if not (x0 <= x < x1 and y0 <= y < y1):
                    raise VerificationError('pixel changed outside allowed rectangle')
                changes += 1
    if not changes:
        raise VerificationError('approved map change absent')
    return changes


def inspect_map_container(data):
    """Check the observed CTEX and single-chunk lossless WebP envelope.

    This deliberately does not claim to parse the compressed VP8L stream.
    """
    if len(data) < 81 or data[:52] != CTEX_HEADER:
        raise UnsupportedFormat('unsupported CTEX fixed header or truncated envelope')
    embedded_size = struct.unpack_from('<I', data, 52)[0]
    if data[56:60] != b'RIFF' or data[64:72] != b'WEBPVP8L':
        raise VerificationError('unsupported RIFF/WEBP/VP8L structure')
    riff_size = struct.unpack_from('<I', data, 60)[0]
    chunk_size = struct.unpack_from('<I', data, 72)[0]
    if (embedded_size != len(data) - 56 or riff_size != len(data) - 64 or
            chunk_size < 5 or 76 + chunk_size + (chunk_size & 1) != len(data)):
        raise VerificationError('inconsistent RIFF or single VP8L chunk length')
    if chunk_size & 1 and data[-1] != 0:
        raise VerificationError('invalid RIFF padding')
    if data[76] != 0x2f:
        raise VerificationError('invalid VP8L signature')
    header = struct.unpack_from('<I', data, 77)[0]
    width = (header & 0x3fff) + 1
    height = ((header >> 14) & 0x3fff) + 1
    alpha = (header >> 28) & 1
    version = header >> 29
    if (width, height) != MAP_SIZE or alpha != 1 or version != 0:
        raise VerificationError('unexpected VP8L dimensions, alpha flag or version')
    return {'width': width, 'height': height, 'alpha_flag': alpha, 'version': version}


_DECODE = '''extends SceneTree
func _initialize() -> void:
 for name in ["original", "candidate"]:
  var tex := ResourceLoader.load("res://" + name + ".ctex", "", ResourceLoader.CACHE_MODE_IGNORE) as CompressedTexture2D
  if tex == null:
   printerr("UNSUPPORTED_TEXTURE"); quit(1); return
  var img := tex.get_image()
  if img == null or img.get_width() != 1587 or img.get_height() != 941 or img.has_mipmaps():
   printerr("UNSUPPORTED_DIMENSIONS_OR_MIPMAPS"); quit(1); return
  if img.is_compressed() and img.decompress() != OK:
   printerr("UNSUPPORTED_COMPRESSION"); quit(1); return
  img.convert(Image.FORMAT_RGBA8)
  var raw := img.get_data()
  if raw.size() != 1587 * 941 * 4:
   printerr("UNSUPPORTED_RGBA"); quit(1); return
  var file := FileAccess.open("/work/" + name + ".rgba", FileAccess.WRITE)
  if file == null:
   printerr("OUTPUT_FAILED"); quit(1); return
  file.store_buffer(raw)
  file.close()
 print("ASSET_DECODE_OK")
 quit(0)
'''


def decode_map(original, candidate, godot):
    """Use the pinned official decoder against the actual PCK entry bytes."""
    if not shutil.which('bwrap') or not Path(godot).is_file() or script_localize.sha_file(Path(godot)) != GODOT_SHA:
        raise UnsupportedFormat('pinned Godot or sandbox unavailable')
    with tempfile.TemporaryDirectory(prefix='asset-verify-') as tmp:
        root = Path(tmp)
        (root / 'project.godot').write_text('config_version=5\n[application]\nconfig/name="AssetVerify"\n')
        (root / 'decode.gd').write_text(_DECODE)
        (root / 'original.ctex').write_bytes(original)
        (root / 'candidate.ctex').write_bytes(candidate)
        command = [shutil.which('bwrap'), '--unshare-all', '--uid', '0', '--gid', '0', '--die-with-parent',
                   '--clearenv', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
                   '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64', '--ro-bind', '/etc', '/etc',
                   '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/private',
                   '--bind', str(root), '/work', '--ro-bind', str(Path(godot).resolve()), '/godot',
                   '--setenv', 'HOME', '/private', '--setenv', 'XDG_DATA_HOME', '/private/data',
                   '--setenv', 'XDG_CONFIG_HOME', '/private/config', '--setenv', 'XDG_CACHE_HOME', '/private/cache',
                   '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'PATH', '/usr/bin:/bin', '--chdir', '/work',
                   '/godot', '--headless', '--path', '/work', '--script', 'res://decode.gd']
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UnsupportedFormat('isolated decoder unavailable or timed out') from exc
        if run.returncode or 'ERROR:' in run.stdout or 'ERROR:' in run.stderr or 'ASSET_DECODE_OK' not in run.stdout:
            raise UnsupportedFormat('official decoder could not safely decode both textures')
        paths = [root / 'original.rgba', root / 'candidate.rgba']
        if any(not p.is_file() or p.stat().st_size != MAP_SIZE[0] * MAP_SIZE[1] * 4 for p in paths):
            raise UnsupportedFormat('decoder RGBA output missing or invalid')
        return tuple(p.read_bytes() for p in paths)


def verify(original_pck, final_pck, plan_path, godot):
    raw, plan = read_plan(plan_path)
    packs = (Path(original_pck).resolve(), Path(final_pck).resolve())
    expected = (plan['original_pck_sha256'], plan['final_pck_sha256'])
    if any(script_localize.sha_file(p) != h for p, h in zip(packs, expected)):
        raise VerificationError('PCK binding mismatch')
    indices = tuple(funeral.inspect_pck(p) for p in packs)
    results = []
    for asset in plan['assets']:
        name = asset['entry']
        try:
            old, new = (_entry(p, i, name) for p, i in zip(packs, indices))
            if asset['kind'] == 'fontdata':
                if _sha(new) != FONT_APPROVED:
                    raise VerificationError('replacement font differs from recorded import')
                results.append({'entry': name, 'status': 'unsupported',
                                'reason': 'fontdata 구조와 원본→최종 보호 필드는 검사하지 못함',
                                'recorded_import_bytes_match': True, 'license_distribution_verified': False})
                continue
            if _sha(old) != MAP_OLD or _sha(new) != MAP_APPROVED:
                raise VerificationError('map entry differs from approved original or final bytes')
            old_metadata = inspect_map_container(old)
            new_metadata = inspect_map_container(new)
            if old_metadata != new_metadata:
                raise VerificationError('VP8L header changed')
            old_rgba, new_rgba = decode_map(old, new, godot)
            changed = compare_rgba(old_rgba, new_rgba, *MAP_SIZE, MAP_RECT)
            results.append({'entry': name, 'status': 'unsupported', 'pixel_status': 'passed',
                            'container_status': 'passed', 'changed_pixels': changed,
                            'allowed_rect': list(MAP_RECT), 'alpha_changes': 0, 'outside_changes': 0,
                            'reason': 'VP8L 내부 비트스트림의 소비 범위·비픽셀 정보는 검증하지 못함',
                            'scope': '기본 레벨 RGBA와 고정 헤더·단일 VP8L 컨테이너만 확인'})
        except UnsupportedFormat as exc:
            results.append({'entry': name, 'status': 'unsupported', 'reason': str(exc)})
        except VerificationError as exc:
            results.append({'entry': name, 'status': 'failed', 'reason': str(exc)})
    if Path(plan_path).read_bytes() != raw or any(script_localize.sha_file(p) != h for p, h in zip(packs, expected)):
        raise VerificationError('input changed during verification')
    status = 'failed' if any(x['status'] == 'failed' for x in results) else 'incomplete' if any(x['status'] == 'unsupported' for x in results) else 'passed'
    return {'status': status, 'assets': results,
            'limitations': ['지도 VP8L 내부 비트스트림 전체의 비픽셀 정보는 검증하지 않았다.',
                            '글꼴 보호 필드와 배포 라이선스는 검증하지 않았다.',
                            '지도 승인·표시 분류는 기존 근거를 신뢰하며 실게임과 Windows는 검증하지 않았다.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True)
    parser.add_argument('--final', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--godot', required=True)
    args = parser.parse_args()
    try:
        result = verify(args.original, args.final, args.plan, args.godot)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'passed' else 1
    except (OSError, VerificationError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
