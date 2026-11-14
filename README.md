# Funeral for the Sun 한글 패치

한글 패치의 설치·복구 런타임과 제작 도구 소스를 제공합니다. 설치에 필요한 패치 데이터는 [Releases의 ZIP](https://github.com/yoodong724/funeral-for-the-sun-ko/releases/tag/steam-26666647)으로 제공합니다.

## 적용 대상 Steam 빌드

- **Steam 빌드 ID: `26666647`** / Steam AppID `4088360`
- 게임 내부 버전: 별도 표기를 확인하지 못했습니다. Steam 빌드 ID와 다른 값입니다.
- 지원 환경: Windows 11, 기본 Windows PowerShell 5.1. 별도 Python 설치나 실행 중 다운로드가 필요하지 않습니다.
- 패치 파일: **`funeral-for-the-sun-ko-26666647.zip`** (약 64 MiB)
- SHA-256: `641da36e2b0b9d3ed1bd1fe156aae40a6e4b8b47dbc8180fe5d10a733ee1a498`

설치기는 실행 파일과 PCK가 지정된 SHA-256과 일치할 때만 설치합니다. 게임 업데이트나 다른 모드로 파일이 달라지면 설치되지 않습니다. 로컬 드라이브 경로와 여유 공간 11GB 이상이 필요합니다. 네트워크·WSL 경로는 지원하지 않습니다.

## 마지막 릴리스 이후 업데이트 내역

Steam 빌드 **26666647** 게임 업데이트에 대응했습니다.

- 새로 추가된 대사 2문구와 수정된 대사 2문구의 번역을 반영했습니다.
- 위치가 바뀐 길 안내 2곳의 기존 번역과 한글 글꼴을 새 위치에 맞췄습니다.
- 게임의 새 장면 데이터와 인물 이미지 수정을 유지했습니다. 기존 번역과 이름·단서 표기도 유지합니다.
- Windows 실기 확인: PowerShell 5.1에서 실제 설치·복구·재설치 6단계를 통과했습니다. Vulkan 옵션으로 메뉴·설정·초반 대표 대사의 한글 표시를 확인했습니다. HJ-PC에서 기본 OpenGL/ANGLE 실행은 회색 창에 머물렀으며 원인은 확정하지 못했습니다.
- 변경분 문맥·장면 이식·PCK 바이트·차분 재구성 해시와 패키지 구성을 확인했습니다. 이번 빌드 전체 완주와 모든 기존 세이브의 호환성을 새로 검증한 것은 아닙니다. 이전 빌드의 사용자 완주 보고는 이번 빌드의 완주 검증으로 간주하지 않습니다.

알려진 현상: 도입 진행 중 저장한 뒤 불러오면 검은 화면이 남는 현상이 원본과 이전 후보 양쪽에서 관찰됐습니다. 원인은 확정하지 않았습니다. 도입을 마친 뒤 저장하세요.

## 설치 방법

1. [Releases](https://github.com/yoodong724/funeral-for-the-sun-ko/releases/tag/steam-26666647)에서 `funeral-for-the-sun-ko-26666647.zip`을 내려받습니다. GitHub의 자동 생성 `Source code` 압축 파일은 설치용이 아닙니다.
2. 게임과 런처 업데이트, 모드 관리자 등 게임 파일을 바꿀 수 있는 프로그램을 종료합니다.
3. 이전 패치가 있으면 이전 버전의 `KoreanPatch/restore.cmd`로 먼저 복구합니다. 패치가 설치된 채 게임 업데이트를 마쳐 복구가 실패한다면 Steam 파일 무결성 검사로 원본을 복원한 뒤 새 패치를 설치하세요. 이전 `backup`·`state`를 새 패치 폴더에 옮기거나 두 폴더를 합치지 마세요.
4. ZIP의 `KoreanPatch` 폴더를 게임 설치 폴더에 넣습니다. `funeralforthesun.exe`, `funeralforthesun.pck`와 `KoreanPatch`가 같은 위치에 있어야 합니다.
5. `KoreanPatch/install.cmd`를 실행하고 경고를 확인한 뒤 진행합니다. 끝날 때까지 창을 닫거나 PC를 끄지 마세요.
6. 게임을 실행합니다. **영어 표시를 한국어로 대체**하므로 별도 언어 선택은 필요하지 않습니다.

영어로 복구하거나 패치를 제거하려면 게임과 관련 프로그램을 종료한 뒤 현재 패치의 `KoreanPatch/restore.cmd`를 실행합니다. 복구가 끝나기 전에 `backup`이나 `state`를 직접 지우지 마세요. 게임 업데이트 전에도 먼저 복구하세요.

작업이 중단되면 게임을 실행하지 말고 `restore.cmd`로 복구를 시도하세요. 복구할 수 없으면 Steam 파일 무결성 검사 또는 게임 재설치로 원본을 복원하세요.

게임이 회색 창에서 멈춘다면 Steam의 게임 속성 → 일반 → 시작 옵션에 아래 내용을 넣어 실행해 보세요. HJ-PC에서는 이 옵션으로 메뉴·설정·초반 한글을 확인했습니다. 다른 PC·그래픽 환경의 동작까지 확인한 것은 아닙니다.

```text
--rendering-method mobile --rendering-driver vulkan --windowed --resolution 1280x720
```

## 누적 업데이트 내역

<details>
<summary>변경 내역 펼치기</summary>

- **2026-11-15 / Steam 빌드 `26666647` / 게임 내부 버전 미확인:** 게임 업데이트 대응, 신규·수정 대사 번역과 이동한 길 안내 수정.
- **2026-11-14 / Steam 빌드 `26643719` / 게임 내부 버전 미확인:** 첫 공개. 096 최종 후보 기반 한글패치, 사용자 완주 테스트 보고 반영. 사용자 완주 검증 완료를 반영한 첫 정식 릴리스.

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
python -B runtime/windows/build_package.py --spec release/patch-spec.json --game /path/to/original-game --payload-dir input --readme release/README.ko.txt --out dist/funeral-for-the-sun-ko-26666647.zip --date 2026-11-15
```

원본 PCK SHA-256: `2b98df6dc566bd8a8e852978e9e77685ef311c89731496db12eb1e0d04afd11f`

최종 PCK SHA-256: `7f1eb40e5a25eb09a91e0cf0a863ab800d1d8e087c076333a5dfc5ca0df6f1fc`

COPY/ADD 차분은 원본에서 같은 64바이트 이상 구간을 찾아 COPY로 바꾸며, 적용 결과의 해시와 남은 ADD 구간의 최소성을 검사합니다. 이 기술 검사가 게임 리소스의 전체 의미·권한·저장 호환성을 입증하지는 않습니다.
