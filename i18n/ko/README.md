<!--
  English version: README.md
  이 문서는 README.md의 한국어 번역본입니다.
  코드 블록, 명령어, URL, 경로, 식별자는 원문 그대로 유지합니다.
-->

*Read this in other languages: [English](../../README.md)*

<p align="center">
  <img src="../../logo-lockup.png" width="520" alt="OpenOrbit" />
</p>

# OpenOrbit이란?

> **AI 페르소나가 제품의 일을 찾고, AI 코딩 에이전트가 변경안을 준비하며,
> 팀이 결과를 검토하는 로컬 워크스페이스입니다.**

OpenOrbit은 AI 에이전트 자체를 평가하는 데 그치지 않고, AI 제품을 둘러싼 일을 운영하는 로컬 우선 웹서비스입니다. 페르소나는 제품을 탐색하며 문제와 과제를 보고하고 증거를 남깁니다. 여러분이 선택한 AI 코딩 에이전트는 격리된 Git worktree에서 변경안을 준비하고, 팀은 하나의 컨트롤룸에서 diff·증거·결정을 검토합니다.

반복적인 AI Agent 평가와 자가 개선도 지원합니다. 실행, 제안, 의사결정, 승인된 변경은 모두 보존되는 운영 이력이 됩니다. 모든 것은 로컬에서 실행되고 기록은 AppData에 남습니다.

## 왜 OpenOrbit인가?

AI 기능이나 웹 제품은 데모에서는 정상으로 보이더라도 프롬프트, 모델, 도구, 제품 변경 이후 성능이 저하될 수 있습니다. OpenOrbit은 보고된 문제를 검토 가능한 개선으로 바꾸는 데 필요한 사람, 페르소나, 코딩 에이전트, 증거를 연결합니다.

```mermaid
flowchart LR
  A[AI 페르소나가<br/>제품을 탐색]
  B[문제, 과제, 보존된 증거]
  C[AI 코딩 에이전트가<br/>worktree 변경안을 준비]
  D[diff, 증거, 제안 검토]
  E[사람의 결정]
  F[개선된 제품 또는<br/>AI Agent]

  A --> B --> C --> D --> E --> F --> A
```

OpenOrbit은 이 일을 투명하고 되돌릴 수 있게 남깁니다. AI는 일을 제안하고 준비할 수 있지만, 적용 여부는 사람이 결정합니다.

## 할 수 있는 일

- **보고된 문제를 worktree로 개발합니다.** AI가 구체적인 문제를 보고하면 코딩 에이전트가 격리된 변경안을 준비하게 하고, 적용 전에 diff와 증거를 검토합니다.
- **원하는 AI 코딩 에이전트를 사용합니다.** 특정 제공자에 묶이지 않고 팀이 이미 사용하는 코딩 에이전트를 연결합니다.
- **AI 페르소나에게 일을 맡깁니다.** 페르소나는 정해진 관점에서 제품을 탐색하고, 과제와 문제를 발견하며, 그 일을 증거와 연결합니다.
- **AI Agent를 지속적으로 개선합니다.** 반복 평가가 응답, 피드백, 제안, 결정을 보존하므로 AI Agent를 안전하게 개선할 수 있습니다.
- **페르소나와 재사용 가능한 자산을 관리합니다.** 다음 작업에 사용할 페르소나, 모델 프로필, 프롬프트, 테스트 케이스, 환경, 워크플로를 관리합니다.
- **Orbit Assistant로 질문하고 조작합니다.** 현재 보고 있는 화면에 관해 묻고, 컨트롤룸을 조작하는 데 도움을 받습니다.
- **MCP와 OpenAPI로 자동화합니다.** 여러분의 에이전트와 도구가 같은 로컬 운영 데이터를 읽고 지원되는 작업을 자동화할 수 있습니다.

## Quick start

가이드 템플릿으로 시작한 뒤, 팀이 운영하려는 제품, 페르소나, AI 워크플로에 맞게 조정하세요.

![OpenOrbit dashboard opening the Agent self-improvement Quick Start](../../docs/images/openorbit-quick-start.gif)

### Quick Start로 10초 만에 시작하기

Dashboard의 **Quick starts**를 열고 가이드 템플릿을 선택한 뒤, 타깃별 필드를 채우고 빌드를 생성하세요. 템플릿은 필요한 러너, 테스트 케이스, 환경, 정책, 모델 프로필을 연결하므로 동작하는 워크플로에서 시작해 필요한 만큼 다듬을 수 있습니다.

| Quick Start | 사용 시점 | 첫 실행 예시 |
| --- | --- | --- |
| **User journey smoke test** | 로컬 제품에 대한 반복적이고 읽기 전용인 브라우저 점검이 필요할 때. | 홈 페이지가 로드되고 주요 제목(heading)이 보이는지 확인합니다. |
| **Site exploration review** | 안전한 동일 사이트 탐색으로부터 증거 기반 제품 피드백을 얻고 싶을 때. | 문서나 대시보드를 탐색하고, 각 권장 사항 뒤에 방문한 페이지를 보존합니다. |
| **Agent self-improvement** | 실제 AI 응답으로부터 관리형 프롬프트를 개선하고 싶을 때. | 구성된 타깃 모델에 지원 요청을 보내고, 그 응답을 보존한 뒤, 감독자가 응답에 근거한 프롬프트 변경만 승인하도록 합니다. |
| **AI SLO and behavior drift monitor** | 품질, 안전성, 지연 시간, 비용에 대한 구조화된 평가기를 이미 갖추고 있을 때. | 해당 probe 명령을 연결하고, 보존된 지표를 구성된 기준선 및 임계값과 비교합니다. |

예를 들어, 지원 에이전트 프롬프트를 평가하려면:

1. **Agent self-improvement** 를 선택합니다.
2. Git 저장소와 관리형 프롬프트 파일을 선택한 뒤, AI 모델 프로필을 고릅니다.
3. 대표적인 사용자 요청 하나와 그 응답 수준의 수용 기준을 입력합니다.
4. 빌드를 생성하고 실행합니다. OpenOrbit는 실제 타깃 AI 응답을 보존하고, 감독자에게 그 증거를 검토하도록 요청하며, 다음 반복에서 채택된 되돌릴 수 있는 프롬프트 개선만 적용합니다.

Quick Start는 제공자 키를 절대 저장하지 않습니다. 선택한 모델 프로필에 이미 구성된 환경 변수 이름을 참조할 뿐입니다.

## 제품 둘러보기

OpenOrbit의 웹 컨트롤룸은 문제 발견부터 결정까지의 일을 한곳에 모읍니다. 현재 내비게이션은 팀이 수행하는 작업을 중심으로 구성되어 있습니다.

| 영역 | 여기서 하는 일 |
| --- | --- |
| **Dashboard** | 현재 활동을 확인하고 가이드 워크플로를 시작합니다. |
| **Assets** | 재사용할 페르소나, 모델 프로필, 프롬프트, 테스트 케이스, 환경, 러너, 워크플로를 관리합니다. |
| **Builds** | 제품 또는 AI Agent 워크플로에 사용할 자산과 정책을 연결합니다. |
| **Runs** | 실행과 그 실행이 남긴 증거를 확인합니다. |
| **Improvements** | 피드백과 페르소나 여정을 살피고, AI가 보고한 이슈와 worktree 제안을 검토합니다. |
| **Settings** | 모델, 코딩 에이전트, 로컬 컨트롤룸을 설정합니다. |

아래 화면은 보존된 증거가 검토 가능한 AI 생성 변경안으로 이어지는 과정을 보여줍니다.

### 실행의 증거 확인하기

보존된 실행(run)을 열어 워크플로, 라이프사이클 진행 상태, 각 단계에서 수집된 증거를 검토하세요. 그런 다음 관찰된 동작을 감독자 피드백 및 제안된 개선안과 비교하세요.

![OpenOrbit Runs showing a completed workflow and its retained evidence](../../docs/images/evaluation-result-approved.png)

### 개선과 페르소나 활동 살펴보기

여러 빌드에 걸쳐 피드백, 의사결정, 점수, 실행 상태, 페르소나 여정을 비교하세요. 이 이력은 제품 또는 AI Agent 워크플로가 시간에 따라 나아지고 있는지 보여줍니다.

![OpenOrbit improvements with feedback trends and proposal-decision history](../../docs/images/improvement-cycle-healthy.png)

### 적용 전 AI가 만든 작업 검토하기

보존된 증거가 구체적인 변경을 뒷받침하면 AI 코딩 에이전트가 격리된 worktree에서 제안을 준비할 수 있습니다. 근거, 수용 증거, diff를 검토한 뒤 승인하거나, 거절하거나, 계속 검토 상태로 둘 수 있으며, 결정 없이는 어떤 변경도 적용되지 않습니다.

![OpenOrbit Improvements reviewing an AI-created change and its isolated worktree diff](../../docs/images/ai-created-proposal-review.png)

### 현재 화면에 관해 Orbit Assistant에게 묻기

System AI 모델을 구성하면 Orbit Assistant에게 현재 보고 있는 화면을 질문하고 컨트롤룸 조작을 도움받을 수 있습니다. 여러분의 AI 에이전트도 OpenOrbit의 MCP 서버 또는 버전 관리 API를 통해 같은 로컬 운영 데이터와 함께 작업할 수 있습니다.

![OpenOrbit Chat Assistant asking what to improve next for a build](../../docs/images/chat-assistant-question.png)

## 설치 및 개발

### 요구 사항

| 요구 사항 | 버전 | 용도 |
| --- | --- | --- |
| Python | 3.13+ | 로컬 API 및 러너 SDK |
| Git | 2.40+ 권장 | Git 설치 및 저장소 기반 평가 사이클 |
| Node.js | 24+ | Git에서 설치 및 프런트엔드 개발 |

### 러너 SDK 문서

러너 SDK 레퍼런스는 Python 모듈과 그 docstring으로부터 생성됩니다. 로컬에서 미리 보려면:

```bash
pnpm run docs:serve
```

`pnpm run docs:build`로 정적 문서 사이트를 빌드하거나, `pnpm run build`를 실행해 SDK 문서와 컨트롤룸 UI를 함께 생성하세요.

### 패키지 앱 실행

일반 패키지 릴리스는 OpenOrbit을 설치한 뒤 바로 실행합니다.

```bash
python -m pip install openorbit
orbit run
```

wheel에는 번들된 컨트롤룸 UI가 이미 포함되어 있으므로, 런타임에 Node.js와 pnpm이 필요하지 않습니다. 시작한 뒤 `http://127.0.0.1:3000`을 여세요. 해당 포트가 사용 중이면 OpenOrbit는 다음으로 사용 가능한 포트를 선택하고 그 URL을 출력합니다.

프로젝트나 원하는 디렉터리와 함께 하나의 컨트롤룸 운영 데이터를 보관하려면 `run`에 해당 디렉터리를 전달하세요. OpenOrbit는 그 안에 `.orbit` 하위 디렉터리를 만들어 사용합니다.

```bash
orbit run .            # 현재 디렉터리의 .orbit/에 저장
orbit run ./my-project # ./my-project/.orbit/에 저장
```

특정 리스너가 필요하면 `ORBIT_PORT`와 `ORBIT_HOST`를 설정하세요.

```bash
ORBIT_PORT=8787 ORBIT_HOST=0.0.0.0 orbit run
```

### 다른 실행 방법

최신 개발 버전을 사용하려면 OpenOrbit 메인 저장소에서 직접 설치하세요. 이 소스 설치에는 Node.js 24+와 pnpm이 필요합니다.

```bash
python -m pip install "openorbit @ git+https://github.com/forthfate/openorbit.git@main"
```

또는 npm으로 한 번 실행합니다.

```bash
npx openorbit run
```

> PyPI 배포는 insighta cloud Inc.의 지원으로 이루어집니다.

### 이 저장소에서 실행

```bash
git clone https://github.com/forthfate/openorbit.git
cd openorbit

uv sync --extra dev
corepack enable
pnpm install
pnpm run build
pnpm run run
```

프런트엔드 개발 시에는 API와 Vite를 따로 시작합니다.

```bash
uv run uvicorn app.main:app --app-dir backend --reload --port 3000
pnpm --filter agent-improvement-console-ui run dev
```

그런 다음 터미널에 표시된 Vite URL(보통 `http://localhost:5173`)을 엽니다.

## Standalone 및 BYOA

OpenOrbit는 독립 실행형(standalone)이며 로컬 우선(local-first) 컨트롤 플레인입니다. AI 모델을 호스팅하거나 재판매하지 않으며, OpenOrbit 클라우드 계정을 요구하지도 않습니다.

여러분의 AI를 가져오세요(Bring your own AI): 팀이 이미 사용하는 API 제공자와 모델에 대한 모델 프로필을 만든 뒤, 그 프로필을 감독자 평가, Cycle Improvement AI, 또는 Chat Assistant에 선택하세요. OpenOrbit는 제공자 자격 증명에 대해 환경 변수 이름만 저장하며 자격 증명 자체는 저장하지 않고, 운영 기록을 여러분의 로컬 AppData에 보관합니다.

### 브라우저 여정 (선택)

브라우저 여정을 실행하는 빌드만 Chromium 브라우저와 플랫폼별 시스템 라이브러리가 필요합니다. OpenOrbit를 시작하거나, 자산을 생성하거나, 실행을 검토하거나, 브라우저가 아닌 러너를 사용하는 데에는 필요하지 않습니다.

## 핵심 개념

> Build는 운영 루프를 정의하고, Test는 이를 한 번 점검하며, Run은 발생한 일을 보존합니다. Supervisor는 증거를 피드백과 제안으로 바꾸고, 다음 변경은 팀이 결정합니다.

| 개념 | 의미 |
| --- | --- |
| **Asset** | 재사용 가능한 모델 프로필, 러너, 워크플로, 프롬프트, 테스트 세트, 또는 환경. |
| **Build** | 자산을 하나의 AI 시스템 평가에 연결하는, 버전이 관리되는 운영 구성. |
| **Test** | 빌드를 검증하기 위해 사용하는 일시적이고 일회성인 실행. |
| **Run** | 단계, 증거, 로그, 의사결정을 포함하여 보존되는 실행 기록. |
| **Supervisor** | 구조화된 평가 결과, 이슈, 제안을 생성하는 AI 검토 단계. |
| **Improvement cycle** | 여러 평가와 사람의 의사결정에 걸친 증거 기반 PDCA 루프. |

## 안전성과 로컬 데이터

OpenOrbit는 로컬 우선입니다. 기본적으로 운영 상태는 저장소 바깥, 플랫폼 AppData에 저장됩니다.

- Windows: `%LOCALAPPDATA%\Orbit`
- macOS: `~/Library/Application Support/Orbit`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/orbit`

`orbit run PATH`를 사용하면 `PATH/.orbit`에 데이터를 보관합니다. 이 경로는 해당 실행에서 기존에 선택한 데이터 위치와 `ORBIT_APP_DATA`보다 우선합니다. Git으로 관리하지 않을 데이터라면 대상 프로젝트의 `.gitignore`에 `.orbit/`을 추가하세요. 명령줄 경로 없이 다른 위치를 사용하려면 `ORBIT_APP_DATA`를 설정하세요. 모델 프로필은 비밀 값이 담긴 환경 변수의 이름을 저장하며, 비밀 값 자체는 절대 저장하지 않습니다. 프로덕션 AI 시스템을 연결하기 전에 워크플로 명령, 승인된 워크스페이스 경계, 네트워크 노출을 검토하세요.

## API 및 확장성

OpenOrbit는 로컬의, 버전이 관리되는 API를 노출합니다.

- Swagger UI: `http://localhost:3000/api/docs`
- OpenAPI 문서: `http://localhost:3000/api/openapi.json`
- API base: `http://localhost:3000/api/v1`
- MCP(Streamable HTTP): `http://localhost:3000/mcp/`

MCP 클라이언트는 `http://localhost:3000/mcp/`에 연결하면 프로젝트와 파이프라인을 조회하고, 실행·승인 작업 및 개선안 수명주기를 다룰 수 있습니다. `openorbit://openapi` 리소스는 전체 v1 HTTP API의 OpenAPI 계약을 제공합니다. MCP도 로컬 전용이며 기본 인증을 제공하지 않으므로, 신뢰할 수 없는 네트워크에 직접 노출하지 마세요.

MCP 또는 버전 관리 OpenAPI를 사용하면 여러분의 에이전트를 연결하고, 같은 로컬 운영 데이터로 지원되는 작업을 자동화할 수 있습니다. 엔드포인트 세부 정보는 [API 레퍼런스](../../docs/API.md)를 참고하세요. 재사용 가능한 자동화를 추가하려면 명시적인 라이프사이클 단계를 갖는 Python 러너를 생성하세요.

```python
from orbit_sdk import runner

@runner.phase("execute")
def verify(ctx):
    ctx.log("Run one bounded evaluation step")

if __name__ == "__main__":
    runner.main()
```

러너는 컨트롤 플레인에 증거를 제공하며, 자체 스케줄러를 시작하거나 타깃 시스템을 조용히 수정하지 않습니다.

## 함께 만들어요

우리는 AI 시스템이 관찰 가능하고, 통제 가능하며, 지속적으로 개선되어야 한다는 믿음을 공유하는 사려 깊은 협력자를 찾고 있습니다. 특히 에이전트 하네스, 브라우저 평가(Playwright 포함), 로컬 자동화, 증거 기반 운영 루프 분야에서 일하는 분들의 기여를 환영합니다. 포크를 시작하거나, 작은 이슈를 열거나, 문서를 개선하거나, 더 큰 아이디어를 함께 다듬어 주세요. 모든 기여를 환영합니다.

프로젝트가 처음이신가요? [good first issues](https://github.com/forthfate/openorbit/labels/good%20first%20issue)를 둘러보거나, [Issues](https://github.com/forthfate/openorbit/issues)에서 질문하거나 아이디어를 나누고, 풀 리퀘스트를 열기 전에 [기여 가이드](CONTRIBUTING.md)를 읽어 보세요.

## 기여하기

기여를 환영합니다. 버그 리포트, 평가 러너 템플릿, 문서 개선, 제품 피드백 모두 도움이 됩니다.

```bash
uv run ruff check orbit/ backend/ tests/
PYTHONPATH=backend uv run pytest -q
pnpm --filter agent-improvement-console-ui run lint
pnpm --filter agent-improvement-console-ui run build
```

`main`에 직접 푸시하지 말고 풀 리퀘스트를 열어 주세요. 개발, 검사, 릴리스 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

## 개발 파트너

<table>
  <tr>
    <td align="center" width="240">
      <a href="https://insighta.cloud">
        <img src="../../docs/images/insighta-cloud-icon.png" width="72" alt="insighta cloud Inc. logo" />
        <br /><br />
        <strong>insighta cloud Inc.</strong>
        <br />
        <sub>Development partner</sub>
      </a>
    </td>
  </tr>
</table>

## 라이선스

Copyright © 2026 forthfate and insighta cloud Inc.

[MIT License](../../LICENSE)로 배포됩니다.
