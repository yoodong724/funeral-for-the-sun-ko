Funeral for the Sun 한글 패치 — Steam 빌드 26643719

대상 및 지원 환경
- Steam AppID 4088360, Steam 빌드 ID 26643719 원본 전용입니다.
- 게임 내부 버전은 별도 표기를 확인하지 못했습니다. Steam 빌드 ID와 구분합니다.
- Windows 11 / 기본 Windows PowerShell 5.1. 별도 Python 설치나 실행 중 다운로드가 필요하지 않습니다.
- 파일 이름: funeral-for-the-sun-ko-26643719.zip
- 실행 파일과 PCK가 지정된 SHA-256과 다르면 설치를 거부합니다.
- 로컬 드라이브 경로만 지원합니다. 네트워크·WSL 경로는 지원하지 않습니다.
- 설치 전 게임 드라이브에 여유 공간을 11GB 이상 확보하세요.

이번 공개
- 096 최종 후보의 번역·화면 수정과 동일한 패치 데이터입니다.
- 사용자가 처음부터 끝까지 테스트 플레이를 완료했다고 보고했습니다(2026-11-14).
- 사용자의 완주 검증 완료와 정식 발행 지시에 따라 정식 릴리스로 제공합니다. 전체 보호 자동 검증의 미지원 항목은 남아 있습니다.
- 최종 ZIP의 Windows 설치·복구·재설치 검증 결과와 잔여 사항은 릴리스 페이지에 기록합니다.
- 모든 기존 세이브 호환성을 확인한 것은 아닙니다. 도입 진행 중 저장한 뒤 불러오면 검은 화면이 남는 현상이 원본과 이전 후보 양쪽에서 관찰됐습니다. 원인은 확정하지 않았습니다. 도입을 마친 뒤 저장하세요.

설치 방법
1. 게임과 런처 업데이트, 모드 관리자 등 게임 파일을 바꿀 수 있는 프로그램을 종료합니다.
2. 이전 한글패치가 있으면 이전 KoreanPatch/restore.cmd로 먼저 복구합니다.
3. ZIP의 KoreanPatch 폴더를 게임 설치 폴더 안에 넣습니다.
   funeralforthesun.exe, funeralforthesun.pck와 KoreanPatch가 같은 위치에 있어야 합니다.
4. KoreanPatch/install.cmd를 실행하고 경고를 확인한 뒤 진행합니다.
   작업이 끝날 때까지 창을 닫거나 컴퓨터를 끄지 마세요.
5. 게임을 실행합니다. 영어 표시를 한국어로 대체하므로 별도 언어 선택은 필요하지 않습니다.

복구·업데이트
- 게임과 관련 프로그램을 종료한 뒤 KoreanPatch/restore.cmd를 실행하면 영어로 복구됩니다.
- 복구가 끝나기 전에 KoreanPatch의 backup, state를 직접 지우지 마세요.
- 게임 업데이트 전에는 먼저 복구하세요. 업데이트된 빌드에는 맞는 새 패치를 사용하세요.
- 작업 중 중단되면 게임을 실행하지 말고 restore.cmd를 시도하세요. 복구할 수 없으면 Steam 파일 무결성 검사 또는 재설치로 원본을 복원하세요.

배포 및 소스
https://github.com/yoodong724/funeral-for-the-sun-ko/releases/tag/steam-26643719
공개 소스만으로는 패치를 재현할 수 없습니다. 게임 원문·번역문·수정 리소스·패치 데이터는 소스 저장소에 포함하지 않습니다.

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
