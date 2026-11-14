#!/usr/bin/env python3
"""Generate and verify a PCK COPY/ADD patch; publish it only after all checks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from project.adapters.delta_pck import RESULT, SOURCE, apply_delta, make_minimality_plan, make_plan, sha


def generate(source, candidate, output):
    source=Path(source).resolve(); candidate=Path(candidate).resolve(); output=Path(output).resolve()
    if output.exists():
        raise FileExistsError('기존 차분을 덮어쓸 수 없음')
    with tempfile.TemporaryDirectory(prefix='kpdif-',dir=output.parent) as folder:
        work=Path(folder); binary=work/'matcher'; plan=work/'plan'; delta=work/'delta'; rebuilt=work/'reconstructed'; check_plan=work/'check-plan'
        subprocess.run(['c++','-O3','-std=c++17','-Wall','-Wextra','-o',str(binary),str(Path(__file__).with_name('delta_match.cpp'))],check=True)
        make_plan(source,candidate,plan)
        run=subprocess.run([str(binary),str(source),str(candidate),str(plan),str(delta)],check=True,capture_output=True,text=True)
        statistics=json.loads(run.stdout)
        apply_delta(source,delta,rebuilt)
        make_minimality_plan(delta,check_plan)
        verify=subprocess.run([str(binary),str(source),str(candidate),str(check_plan),'unused','--verify-only'],check=True,capture_output=True,text=True)
        minimum=json.loads(verify.stdout)
        if (sha(source), sha(candidate)) != (SOURCE, RESULT):
            raise ValueError('검사 중 원본 또는 후보 PCK 변경')
        os.link(delta,output)
        return {'delta_bytes':output.stat().st_size,'result_sha256_verified':True,'statistics':statistics,'minimality':minimum}


def main():
    parser=argparse.ArgumentParser(description='원본 PCK와 후보 PCK의 최소 COPY/ADD 차분 생성')
    parser.add_argument('source');parser.add_argument('candidate');parser.add_argument('output')
    args=parser.parse_args()
    print(json.dumps(generate(args.source,args.candidate,args.output),ensure_ascii=False))

if __name__=='__main__':
    main()
