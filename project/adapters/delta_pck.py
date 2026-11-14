#!/usr/bin/env python3
"""Prepare contiguous PCK COPY/ADD ranges for the exhaustive 64-byte matcher."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from project.adapters.funeral import inspect_pck

SOURCE = 'e51e65809daadf16ab192df266275a8f22ccaf98a3b4627860b50a080c638ed6'
RESULT = 'a72010237c41f4a706a807902dbfd49edf740783b0bcba98b5abe621052f087d'


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def make_plan(source, result, destination, *, verify_hash=True):
    if verify_hash and (sha(source), sha(result)) != (SOURCE, RESULT):
        raise ValueError('원본 또는 후보 PCK 해시 불일치')
    old, new = inspect_pck(source), inspect_pck(result)
    records = []
    cursor = 0
    def add(kind, offset, length, source_offset=0, category=0):
        nonlocal cursor
        if length:
            if offset != cursor:
                raise ValueError('후보 범위가 연속적이지 않음')
            records.append((kind, offset, length, source_offset, category))
            cursor += length
    for name, item in sorted(new.entries.items(), key=lambda pair: pair[1].offset):
        add(1, cursor, item.offset-cursor, category=0)
        before = old.entries.get(name)
        if before and item.md5 == before.md5 and item.size == before.size:
            add(0, item.offset, item.size, before.offset, 0)
        else:
            add(1, item.offset, item.size, category=1 if before else 2)
    add(1, cursor, Path(result).stat().st_size-cursor, category=0)
    with open(destination, 'xb') as f:
        f.write(struct.pack('<Q',len(records)))
        for record in records:
            f.write(struct.pack('<BQQQB',*record))
    return len(records)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('source'); ap.add_argument('result'); ap.add_argument('plan')
    args=ap.parse_args()
    print(json.dumps({'ranges':make_plan(args.source,args.result,args.plan)}))


if __name__ == '__main__':
    main()


def apply_delta(source, patch, destination, expected_source=SOURCE, expected_result=RESULT):
    """Apply the strict COPY/ADD stream to a new destination and verify both hashes."""
    if sha(source) != expected_source:
        raise ValueError('원본 PCK 해시 불일치')
    source_size = Path(source).stat().st_size
    with open(source, 'rb') as old, open(patch, 'rb') as patch_file, open(destination, 'xb') as out:
        def exact(n):
            value = patch_file.read(n)
            if len(value) != n:
                raise ValueError('차분 데이터가 잘림')
            return value
        if exact(8) != b'KPDIF001':
            raise ValueError('차분 형식 오류')
        count, size = struct.unpack('<QQ',exact(16))
        if count > Path(patch).stat().st_size // 9:
            raise ValueError('차분 명령 수 오류')
        digest=hashlib.sha256(); written=0
        for _ in range(count):
            kind=exact(1)[0]
            if kind == 0:
                off,length=struct.unpack('<QQ',exact(16))
                if off > source_size or length > source_size-off:
                    raise ValueError('원본 복사 범위 오류')
                old.seek(off); stream=old
            elif kind == 1:
                length=struct.unpack('<Q',exact(8))[0]; stream=patch_file
            else:
                raise ValueError('차분 명령 오류')
            if not length or length > size-written:
                raise ValueError('차분 결과 크기 오류')
            left=length
            while left:
                b=stream.read(min(left,1024*1024))
                if not b:
                    raise ValueError('차분 또는 원본 데이터가 잘림')
                out.write(b);digest.update(b);left-=len(b)
            written+=length
        if written != size or patch_file.read(1):
            raise ValueError('차분 크기 또는 후행 데이터 오류')
        if digest.hexdigest() != expected_result:
            raise ValueError('결과 PCK 해시 불일치')
    return written


def make_minimality_plan(patch, destination):
    """Reconstruct output ranges from the serialized patch for independent rescanning."""
    ranges=[]
    with open(patch,'rb') as f:
        if f.read(8)!=b'KPDIF001':
            raise ValueError('차분 형식 오류')
        header=f.read(16)
        if len(header)!=16:
            raise ValueError('차분 헤더 오류')
        count, size=struct.unpack('<QQ',header); pos=0
        for _ in range(count):
            k=f.read(1)
            if k==b'\x00':
                data=f.read(16)
                if len(data)!=16: raise ValueError('COPY 잘림')
                off, length=struct.unpack('<QQ',data)
                ranges.append((0,pos,length,off,0))
            elif k==b'\x01':
                data=f.read(8)
                if len(data)!=8: raise ValueError('ADD 잘림')
                length=struct.unpack('<Q',data)[0]
                if length>Path(patch).stat().st_size-f.tell(): raise ValueError('ADD 데이터 잘림')
                f.seek(length,1)
                ranges.append((1,pos,length,0,0))
            else: raise ValueError('차분 명령 오류')
            if not length or length>size-pos: raise ValueError('결과 범위 오류')
            pos+=length
        if pos!=size or f.read(1): raise ValueError('차분 후행 데이터 오류')
    with open(destination,'xb') as f:
        f.write(struct.pack('<Q',len(ranges)))
        for row in ranges:f.write(struct.pack('<BQQQB',*row))
    return len(ranges)
