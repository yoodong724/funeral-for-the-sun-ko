# Funeral for the Sun 한글 패치

한글 패치의 설치·복구 런타임과 제작 도구 소스를 제공합니다. 설치에 필요한 패치 데이터는 [Releases의 ZIP](https://github.com/yoodong724/funeral-for-the-sun-ko/releases/tag/steam-26758003)으로 제공합니다.

## 적용 대상 Steam 빌드

- **Steam 빌드 ID: `26758003`** / Steam AppID `4088360`
- 게임 내부 버전: 별도 표기를 확인하지 못했습니다. Steam 빌드 ID와 다른 값입니다.
- 지원 환경: Windows 11, 기본 Windows PowerShell 5.1. 별도 Python 설치나 실행 중 다운로드가 필요하지 않습니다.
- 패치 파일: **`funeral-for-the-sun-ko-26758003.zip`** (약 64 MiB)
- SHA-256: `ad5e72316235bbb530d6762e982238237c58ac158ff7923684f569097f4c5350`

설치기는 실행 파일과 PCK가 지정된 SHA-256과 일치할 때만 설치합니다. 게임 업데이트나 다른 모드로 파일이 달라지면 설치되지 않습니다. 로컬 드라이브 경로와 여유 공간 11GB 이상이 필요합니다. 네트워크·WSL 경로는 지원하지 않습니다.

## 마지막 릴리스 이후 업데이트 내역

게임 업데이트(Steam 빌드 **26758003**)에 맞춘 첫 릴리스입니다. 직전 릴리스(26732459)의 번역과 수정 사항을 모두 이어받았습니다. 이전 빌드용 패치는 새 빌드에 설치되지 않습니다.

- 이번 게임 업데이트에는 새로 추가되거나 바뀐 화면 문구가 없습니다.
- 게임이 고친 가계도 초상 합치기 동작과 기본 전체 화면 설정에 맞춰, 바뀐 스크립트 3개에 기존 한국어 표시를 다시 적용했습니다.
- 확인 범위: 바뀐 스크립트가 게임 원본을 정확히 재현하는 기준 위에 기존 한국어 수정만 얹었는지 자동으로 확인했습니다. Windows에서 설치·재설치·복구 6단계와 메인 메뉴·설정·저장 슬롯·초반 대사의 한국어 표시를 확인했습니다. 설치·복구 런타임은 이전 릴리스와 같은 파일입니다.
- 가계도 화면 등 진행이 필요한 화면, 전체 완주와 모든 기존 세이브의 호환성은 새로 검증하지 않았습니다. 패키지 안의 안내문에는 Windows 확인 전의 확인 범위가 적혀 있습니다.

알려진 현상: 도입 진행 중 저장한 뒤 불러오면 검은 화면이 남는 현상이 원본과 이전 후보 양쪽에서 관찰됐습니다. 원인은 확정하지 않았습니다. 도입을 마친 뒤 저장하세요.

## 설치 방법

1. [Releases](https://github.com/yoodong724/funeral-for-the-sun-ko/releases/tag/steam-26758003)에서 `funeral-for-the-sun-ko-26758003.zip`을 내려받습니다. GitHub의 자동 생성 `Source code` 압축 파일은 설치용이 아닙니다.
2. 게임과 런처 업데이트, 모드 관리자 등 게임 파일을 바꿀 수 있는 프로그램을 종료합니다.
3. 이전 패치가 있으면 이전 버전의 `KoreanPatch/restore.cmd`로 먼저 복구합니다. 패치가 설치된 채 게임 업데이트를 마쳐 복구가 실패한다면 Steam 파일 무결성 검사로 원본을 복원한 뒤 새 패치를 설치하세요. 이전 `backup`·`state`를 새 패치 폴더에 옮기거나 두 폴더를 합치지 마세요.
4. ZIP의 `KoreanPatch` 폴더를 게임 설치 폴더에 넣습니다. `funeralforthesun.exe`, `funeralforthesun.pck`와 `KoreanPatch`가 같은 위치에 있어야 합니다.
5. `KoreanPatch/install.cmd`를 실행하고 경고를 확인한 뒤 진행합니다. 끝날 때까지 창을 닫거나 PC를 끄지 마세요.
6. 게임을 실행합니다. **영어 표시를 한국어로 대체**하므로 별도 언어 선택은 필요하지 않습니다.

영어로 복구하거나 패치를 제거하려면 게임과 관련 프로그램을 종료한 뒤 현재 패치의 `KoreanPatch/restore.cmd`를 실행합니다. 복구가 끝나기 전에 `backup`이나 `state`를 직접 지우지 마세요. 게임 업데이트 전에도 먼저 복구하세요.

작업이 중단되면 게임을 실행하지 말고 `restore.cmd`로 복구를 시도하세요. 복구할 수 없으면 Steam 파일 무결성 검사 또는 게임 재설치로 원본을 복원하세요.

게임이 회색 창에서 멈춘다면 Steam의 게임 속성 → 일반 → 시작 옵션에 아래 내용을 넣어 실행해 보세요. HJ-PC에서는 이 옵션으로 메뉴·설정·초반 한글을 확인했습니다. 빌드 26758003에서는 이 옵션을 줘도 전체 화면으로 표시됐으며, 게임의 전체 화면 기본값 변경 때문으로 보이지만 원인은 확인하지 않았습니다. 다른 PC·그래픽 환경의 동작까지 확인한 것은 아닙니다.

```text
--rendering-method mobile --rendering-driver vulkan --windowed --resolution 1280x720
```

## 누적 업데이트 내역

<details>
<summary>변경 내역 펼치기</summary>

- **2026-11-19 / Steam 빌드 `26758003` / 게임 내부 버전 미확인:** 게임 업데이트 대응. 새 화면 문구 없음, 동작이 바뀐 스크립트 3개에 기존 한국어 표시 재적용.
- **2026-11-18 / Steam 빌드 `26732459` / 게임 내부 버전 미확인:** 게임 업데이트 대응. 새 '지난 대화' 창 번역, 위치가 바뀐 대화의 기존 번역 유지, 문구가 바뀐 대사·안내 반영.
- **2026-11-17 / Steam 빌드 `26666647` rc1 / 게임 내부 버전 미확인:** 한글 패치만 수정. 화자 착오로 뒤바뀐 반말·존댓말과 장면 간 말투 불일치 대사 수정.
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
python -B runtime/windows/build_package.py --spec release/patch-spec.json --game /path/to/original-game --payload-dir input --readme release/README.ko.txt --out dist/funeral-for-the-sun-ko-26758003.zip --date 2026-11-19
```

원본 PCK SHA-256: `1f6c5b283eb08f3cbc2970c614e1a46323c7b9b2251f30220c83e54681eb6d16`

최종 PCK SHA-256: `7dfa75f565eea6f4dca6a72e499f778c394fd2580b76bc8bfbe17159f14e3fb1`

COPY/ADD 차분은 원본에서 같은 64바이트 이상 구간을 찾아 COPY로 바꾸며, 적용 결과의 해시와 남은 ADD 구간의 최소성을 검사합니다. 이 기술 검사가 게임 리소스의 전체 의미·권한·저장 호환성을 입증하지는 않습니다.
