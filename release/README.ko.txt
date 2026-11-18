Funeral for the Sun 한글 패치 — Steam 빌드 26732459

대상 및 지원 환경
- Steam AppID 4088360, Steam 빌드 ID 26732459 원본 전용입니다.
- Windows 11 / 기본 Windows PowerShell 5.1. 별도 프로그램 설치나 실행 중 다운로드가 필요하지 않습니다.
- 파일 이름: funeral-for-the-sun-ko-26732459.zip
- 실행 파일과 PCK의 SHA-256이 대상 원본과 다르면 설치를 거부합니다.
- Windows 로컬 드라이브 경로를 사용하고, 설치 전 게임 드라이브에 여유 공간을 11GB 이상 확보하세요.

이번 업데이트
- 게임 업데이트(Steam 빌드 26732459)에 맞춘 패치입니다. 26666647 rc1의 번역을 모두 이어받았습니다.
- 새로 생긴 '지난 대화' 창(나무 속 남자와의 대화 다시 보기)의 제목과 버튼을 한국어로 표시합니다.
- 게임에서 문구가 바뀐 대사·안내 7줄과 확인 목록 안내, 길 안내 '폐허'를 반영했습니다.
- 나무 속 남자 대화가 별도 리소스로 옮겨진 것에 맞춰 기존 번역이 그대로 표시되도록 했습니다.

설치 방법
1. 게임과 게임 파일을 바꿀 수 있는 프로그램을 종료합니다.
2. 이전 한글패치가 있으면 이전 KoreanPatch/restore.cmd로 먼저 복구합니다.
   이전 패치가 설치된 채 Steam 업데이트를 마쳤고 복구가 실패한다면,
   Steam의 게임 파일 무결성 검사로 원본을 복원한 뒤 새 패치를 설치하세요.
   이전 KoreanPatch 폴더와 새 폴더를 합치거나 이전 backup/state를 새 패치에 옮기지 마세요.
3. ZIP의 KoreanPatch 폴더를 게임 설치 폴더 안에 넣습니다.
   funeralforthesun.exe, funeralforthesun.pck와 KoreanPatch가 같은 위치에 있어야 합니다.
4. KoreanPatch/install.cmd를 실행하고 경고를 확인한 뒤 진행합니다.
   끝날 때까지 창을 닫거나 컴퓨터를 끄지 마세요.
5. 게임을 실행합니다. 영어 표시를 한국어로 대체하므로 언어 선택은 필요하지 않습니다.

회색 창에서 멈추는 경우
- HJ-PC 실기에서 기본 OpenGL·ANGLE 실행은 회색 창에 머물렀고 Vulkan 실행으로 메뉴와 초반 한글을 확인했습니다.
- 같은 현상이 나타나면 Steam의 게임 속성 → 일반 → 시작 옵션에 아래 내용을 넣어 실행해 보세요.
  --rendering-method mobile --rendering-driver vulkan --windowed --resolution 1280x720
- 이 옵션으로 1280×720 창 모드 표시를 확인했습니다. 다른 PC·그래픽 환경의 동작과 원인은 확정하지 않았습니다.

복구 및 다음 게임 업데이트
- 게임과 관련 프로그램을 종료한 뒤 KoreanPatch/restore.cmd를 실행하면 원본으로 복구됩니다.
- 게임 업데이트 전에는 먼저 복구하고, 업데이트된 빌드에 맞는 패치를 사용하세요.
- 복구가 끝나기 전에 backup/state를 직접 지우지 마세요.
- 작업 중 중단되면 게임을 실행하지 말고 restore.cmd를 시도하세요.
  복구할 수 없으면 Steam 파일 무결성 검사 또는 재설치로 원본을 복원하세요.

확인 범위와 알려진 제한
- 이번 빌드는 바뀐 대사·라벨과 새 '지난 대화' 창이 의도한 한국어·글꼴로 불러와지는지 자동 시험으로 확인했습니다.
- 설치·복구 런타임은 이전 패치에서 Windows로 검증한 동일 파일을 사용합니다. 이번 빌드의 Windows 실기와 실제 게임 화면은 확인하지 않았습니다.
- 전체 완주·'지난 대화' 창의 실제 배치·모든 기존 세이브 호환성은 확인하지 않았습니다.
- 내부 정답·식별자·PageData와 저장 문구는 게임 원문을 유지하고, 화면에서만 번역합니다.
  모든 기존 세이브의 호환성을 보장하는 것은 아닙니다.
- 도입 진행 중 저장한 뒤 불러오면 검은 화면이 남는 현상이 과거 원본과 패치에서 관찰됐습니다.
  도입을 마친 뒤 저장하세요.

글꼴 고지
한글 표시에는 Noto Sans CJK KR 폴백을 사용합니다.
Copyright © 2014–2021 Adobe. SIL Open Font License 1.1.
아래에 글꼴 라이선스 전문을 포함합니다.

This Font Software is licensed under the SIL Open Font License,
Version 1.1.

This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL

-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font
creation efforts of academic and linguistic communities, and to
provide a free and open framework in which fonts may be shared and
improved in partnership with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply to
any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software
components as distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to,
deleting, or substituting -- in part or in whole -- any of the
components of the Original Version, by changing formats or by porting
the Font Software to a new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed,
modify, redistribute, and sell modified and unmodified copies of the
Font Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components, in
Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the
corresponding Copyright Holder. This restriction only applies to the
primary font name as presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created using
the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
