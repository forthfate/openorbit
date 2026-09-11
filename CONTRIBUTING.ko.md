<!--
  English version: CONTRIBUTING.md
  이 문서는 CONTRIBUTING.md의 한국어 요약본입니다.
  전체 규칙과 최신 내용은 항상 영어 원문(CONTRIBUTING.md)을 기준으로 합니다.
  명령어, 경로, 파일명, 식별자는 원문 그대로 유지합니다.
-->

*Read this in other languages: [English](CONTRIBUTING.md)*

# 기여 가이드 (한국어 요약)

이 문서는 [CONTRIBUTING.md](CONTRIBUTING.md)의 시작 절차를 한국어로 요약한 것입니다.
정확하고 최신인 전체 규칙은 항상 영어 원문을 확인하세요.

## 개발 환경 준비

Python 3.13+ 와 Node 24+ 가 필요합니다.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/ruff check orbit/ backend/ tests/
corepack enable
pnpm install
pnpm --filter agent-improvement-console-ui run build
```

패키지형 로컬 앱 경로로 실행하려면 `orbit run`을 사용하세요.

Windows에서는 `.venv\Scripts\Activate.ps1`로 환경을 활성화하고
`.venv\Scripts\python.exe`를 사용하세요.

## UI 스모크 테스트

`frontend/e2e/orbit-ui.spec.ts`가 기대하는 샘플 데이터로 OpenOrbit를 시작한 뒤,
저장소 루트에서 다음을 실행합니다.

```bash
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 pnpm --filter agent-improvement-console-ui exec playwright test
```

앱이 다른 포트를 사용한다면, 실행 중인 앱이 출력한 URL로 `PLAYWRIGHT_BASE_URL`을
설정하세요. 이 값을 생략하거나 비워 두면 테스트는 `http://127.0.0.1:3001`을 사용합니다.
이는 대상 URL만 바꿀 뿐이며, 기존 시나리오는 여전히 구성된 저장소와 샘플 평가
데이터를 필요로 합니다.

## Pre-commit

이 저장소는 커밋 전에 Python은 Ruff로, React는 ESLint로 검사하고,
Vite 프로덕션 빌드로 React 애플리케이션을 검증합니다.

```bash
.venv/bin/pre-commit install
.venv/bin/pre-commit run --all-files
```

React 훅은 `pnpm install`이 한 번 실행되어 있어야 동작합니다.

## 규칙 (요약)

- 공개(public) 동작 번들은 독점 소스, 프롬프트, 픽스처와 독립적으로 유지합니다.
- 선언적 동작 계약은 `orbit/resources/definitions/`, 프롬프트 템플릿은
  `orbit/resources/prompts/`, 비밀이 아닌 샘플 입력은 `orbit/resources/fixtures/`에 둡니다.
- 명령은 반드시 토큰 배열이어야 하며, 셸 문자열 실행을 도입하지 않습니다.
- 동작이나 스키마 변경에는 테스트를 추가합니다.

## 지역화(Localization) (요약)

- 공유되는 정적 UI 문구는 `frontend/src/locales/index.ts`에 두고, 새 사용자 대상
  UI 문자열을 컴포넌트 안에 인라인으로 추가하지 않습니다.
- 새 로케일 키는 영어, 한국어, 일본어 사전 모두에 동일한 중첩 구조와 키 이름으로
  추가합니다. 관련 없는 키를 기존 그룹에 넣지 말고, 기능 단위로 묶습니다.
- 선택된 애플리케이션 로케일(`orbit.locale`)을 소스 오브 트루스로 사용합니다.
  `resolveLocale`은 미지원이거나 누락된 값에 대해 영어로 폴백해야 합니다.
- 로케일 민감성이 있는 날짜, 시간, 숫자 서식에는 `intlLocales`를 사용합니다.
- 런타임 콘텐츠를 로케일 리소스로 취급하지 않습니다. 예를 들어 러너 템플릿이나
  퀵 스타트의 AI 번역은 캐시된 표시용 데이터이며, **Translate**, **Show original**,
  오류 메시지 같은 정적 컨트롤은 로케일 키로 남습니다.
- 번역은 실행 가능하거나 식별성을 갖는 값을 바꿔서는 안 됩니다. ID, 파라미터 키와 값,
  소스 코드, URL, 경로, API 페이로드는 원래 값을 유지합니다.

## 릴리스

릴리스 절차는 보호된 순서를 따르며, 버전 태그가 항상 검증된 `main` 커밋을
가리키도록 합니다. 릴리스를 준비하는 경우 전체 절차는 영어 원문
[CONTRIBUTING.md](CONTRIBUTING.md)의 "Releases" 섹션을 반드시 확인하세요.

---

기여물은 MIT 라이선스로 제공됩니다.
