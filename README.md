# Funeral for the Sun 한글 패치

한글 패치의 설치·복구 런타임과 제작 도구 소스를 제공합니다. 설치에 필요한 패치 데이터는 [Releases의 ZIP](https://github.com/yoodong724/funeral-for-the-sun-ko/releases/tag/steam-26643719)으로 제공합니다.

## 적용 대상 Steam 빌드

- **Steam 빌드 ID: `26643719`** / Steam AppID `4088360`
- 게임 내부 버전: 별도 표기를 확인하지 못했습니다. Steam 빌드 ID와 다른 값입니다.
- 지원 환경: Windows 11, 기본 Windows PowerShell 5.1. 별도 Python 설치나 실행 중 다운로드가 필요하지 않습니다.
- 패치 파일: **`funeral-for-the-sun-ko-26643719.zip`** (약 64 MiB)
- SHA-256: `5226dd9b933072e7dbb76ef6782c234afd5bcc2f43f3eddf739e2fcf6b43cd6f`

설치기는 실행 파일과 PCK가 지정된 SHA-256과 일치할 때만 설치합니다. 게임 업데이트나 다른 모드로 파일이 달라지면 설치되지 않습니다. 로컬 드라이브 경로와 여유 공간 11GB 이상이 필요합니다. 네트워크·WSL 경로는 지원하지 않습니다.

## 마지막 릴리스 이후 업데이트 내역

**첫 공개입니다.** 최종 개발 후보 096의 패치 데이터를 그대로 사용합니다. 게임 업데이트 대응, 회상·조사·안내 문구 번역, 인명·용어 정리, 이동 표지와 가계도 카드의 한글 배치, 아이템 이름 표시와 이름 선택 창 가나다순 정렬을 포함합니다. 추리 판정과 저장에는 원래 내부 이름·아이템 값을 유지하도록 구현했습니다.

- 사용자 검증: 2026-11-14 현재 프로젝트 한글패치로 처음부터 끝까지 테스트 플레이를 마쳤다고 보고했습니다.
- 제작 측 확인: ZIP 무결성과 구성, 096 후보와 payload·런타임·진입점의 바이트 일치, 원본에서 차분으로 재구성한 PCK의 SHA-256을 확인합니다.
- Windows 최종 ZIP 설치·복구·재설치: HJ-PC의 독립된 게임 사본에서 검증 진행 중이며 공개 전에 결과를 갱신합니다.
- 남은 한계: 전체 보호 자동 검증에는 미지원 항목이 남아 있고, 모든 기존 세이브 호환성과 제작 측 최신 후보의 독립 언어·실게임 재검수는 완료하지 않았습니다. **전체 배포 조건을 충족한 것으로 간주하지 않으며 프리릴리스로 제공합니다.**

알려진 현상: 도입 진행 중 저장한 뒤 불러오면 검은 화면이 남는 현상이 원본과 이전 후보 양쪽에서 관찰됐습니다. 원인은 확정하지 않았습니다. 도입을 마친 뒤 저장하세요.

## 설치 방법

1. [Releases](https://github.com/yoodong724/funeral-for-the-sun-ko/releases/tag/steam-26643719)에서 `funeral-for-the-sun-ko-26643719.zip`을 내려받습니다. GitHub의 자동 생성 `Source code` 압축 파일은 설치용이 아닙니다.
2. 게임과 런처 업데이트, 모드 관리자 등 게임 파일을 바꿀 수 있는 프로그램을 종료합니다.
3. 이전 패치가 있으면 이전 버전의 `KoreanPatch/restore.cmd`로 먼저 복구합니다.
4. ZIP의 `KoreanPatch` 폴더를 게임 설치 폴더에 넣습니다. `funeralforthesun.exe`, `funeralforthesun.pck`와 `KoreanPatch`가 같은 위치에 있어야 합니다.
5. `KoreanPatch/install.cmd`를 실행하고 경고를 확인한 뒤 진행합니다. 끝날 때까지 창을 닫거나 PC를 끄지 마세요.
6. 게임을 실행합니다. **영어 표시를 한국어로 대체**하므로 별도 언어 선택은 필요하지 않습니다.

영어로 복구하거나 패치를 제거하려면 게임과 관련 프로그램을 종료한 뒤 현재 패치의 `KoreanPatch/restore.cmd`를 실행합니다. 복구가 끝나기 전에 `backup`이나 `state`를 직접 지우지 마세요. 게임 업데이트 전에도 먼저 복구하세요.

작업이 중단되면 게임을 실행하지 말고 `restore.cmd`로 복구를 시도하세요. 복구할 수 없으면 Steam 파일 무결성 검사 또는 게임 재설치로 원본을 복원하세요.

## 누적 업데이트 내역

<details>
<summary>변경 내역 펼치기</summary>

- **2026-11-14 / Steam 빌드 `26643719` / 게임 내부 버전 미확인:** 첫 공개. 096 최종 후보 기반 한글패치, 사용자 완주 테스트 보고 반영. 전체 보호 자동 검증 미완료로 프리릴리스.

</details>

## 소스와 재현 범위

**이 저장소의 소스 파일만으로는 한글 패치를 재현할 수 없습니다.** 게임 원문 텍스트·이미지·음성, 번역문과 catalog·translations·canonical 작업 파일, 수정한 게임 리소스·PCK와 payload는 소스 저장소에 넣지 않았습니다. 내부 작업 기록과 커밋 이력도 포함하지 않습니다. 설치에 필요한 패치 데이터는 Releases ZIP에 들어 있습니다.

- `runtime/windows/`: 패키지 조립 스크립트와 Windows 설치·복구 런타임.
- `release/`: 패치 사양, 최종 manifest, 패키지 안내문 원본.
- `project/adapters/`: PCK 삽입·차분 생성, Godot 리소스·스크립트 변환과 부분 검증 도구. 공개하지 않은 입력·승인 근거가 필요한 검사는 소스만으로 실행할 수 없습니다. 부분 검사의 성공을 전체 게임 보호 검증으로 해석하지 마세요.
- `scripts/parallel_translations.py`, `toolbox/tools/`: 위 도구의 공통 기술 검사 코드.
- `project/fonts/noto-sans-cjk/OFL.txt`: 패치에 포함한 Noto Sans CJK KR 폴백의 SIL Open Font License 1.1. Copyright © 2014–2021 Adobe.

제작에는 Python 3.11 이상, Linux C++17 컴파일러·mmap, [Godot 4.4.1](https://github.com/godotengine/godot-builds/releases/tag/4.4.1-stable), [GDRE Tools 2.7.4](https://github.com/GDRETools/gdsdecomp/releases/tag/v2.7.4)가 필요합니다. UID 보존용 Godot 소스 패치는 어댑터 폴더에 있습니다. 해당 도구의 실행 파일과 진단용 엔진 빌드는 이 저장소에 포함하지 않습니다.

정확히 일치하는 원본 PCK와 이미 준비된 최종 PCK가 있는 경우 공개 차분 도구로 payload를 만들 수 있습니다. 번역·수정 리소스 제작 단계는 포함되지 않습니다.

```sh
mkdir -p input dist
PYTHONPATH=. python -B project/adapters/delta_generate.py /path/to/original.pck /path/to/localized.pck input/patch.kpd
python -B runtime/windows/build_package.py --spec release/patch-spec.json --game /path/to/original-game --payload-dir input --readme release/README.ko.txt --out dist/funeral-for-the-sun-ko-26643719.zip --date 2026-11-14
```

원본 PCK SHA-256: `e51e65809daadf16ab192df266275a8f22ccaf98a3b4627860b50a080c638ed6`

최종 PCK SHA-256: `a72010237c41f4a706a807902dbfd49edf740783b0bcba98b5abe621052f087d`

COPY/ADD 차분은 원본에서 같은 64바이트 이상 구간을 찾아 COPY로 바꾸며, 적용 결과의 해시와 남은 ADD 구간의 최소성을 검사합니다. 이 기술 검사가 게임 리소스의 전체 의미·권한·저장 호환성을 입증하지는 않습니다.
