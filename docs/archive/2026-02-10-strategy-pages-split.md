# 전략 페이지 분리 계획서 (촘촘 버전)

> ⚠️ **[2026-08-02 갱신] MA5 돌파(MA5/300) 전략은 코드베이스에서 완전 제거되었습니다.**
> 이 문서의 MA5 관련 항목(탭·`ma5-breakout-scan` API·`scanMA5Breakout` 등 JS 함수·
> MA5 스캔 테이블·AC 테스트케이스)은 **모두 무효**입니다. 현재 매수 전략은 골든크로스 단일입니다.
> 배경: 듀얼 MA 변형은 walk-forward 실측상 MA 기간이 엣지가 아님이 확인됨(레짐 게이트만 유효).
> 문서 본문은 당시 계획 이력 보존을 위해 원문 유지.

- 날짜: 2026-02-10
- 대상 리포: `kis-strategy-alert-server`
- 목적: `/mypage/strategy/` 페이지에서 **관리/운영/수정/조회**를 분리하여, **Run & Results 중심**으로 단순화

> SSOT(확정): **전략 목록관리 페이지 URL = `/mypage/strategy/manage`**

---

## 1) 배경/문제정의

### Problem
- 현재 `/mypage/strategy/`는 아래 성격의 기능이 한 화면에 공존
  - (A) 스크리닝 실행 + 결과 확인 (Run & Results)
  - (B) 전략 목록 관리(CRUD)
  - (C) 전략 운영(start/pause/stop/execute/scheduler)
  - (D) 전략 수정(PATCH + Config PATCH)
  - (E) Symbol States 조회
  - (F) Signals + Statistics 조회
- 결과적으로:
  - 사용자가 가장 자주 쓰는 Run 흐름(스크리닝) 진입이 무거워짐
  - 전략 관리/운영/조회 UI가 섞여 있어 오조작 위험(특히 start/stop/execute)
  - JS(`static/js/pages/strategy.js`)가 거대해져 유지보수/리뷰 난이도 상승

### Decision
- `/mypage/strategy/`는 **Run & Results(스크리닝/결과/히스토리)** 중심으로 유지하고, 나머지 5개 영역을 별도 페이지로 분리한다.

### Rationale
- 화면 목적(의도) 단위로 분리하면 학습비용과 오조작을 동시에 줄일 수 있음
- 코드도 “페이지 단위 JS”로 분해되어 변경 영향 범위가 좁아짐

### Alternatives
1) 단일 페이지 유지 + 섹션 접기/탭
   - Pros: URL/라우팅 변경 적음
   - Cons: 여전히 번들/DOM/상태가 커지고, 오조작 리스크 유지
2) 단일 페이지 유지 + 모달로 분리
   - Cons: 모달 상태/검증이 복잡해지고, 깊은 기능(신호/상태 테이블)엔 부적합

### Risks
- 페이지 분리로 “선택된 전략(strategy_id)” 컨텍스트를 페이지 간 전달해야 함
  - 대응: query param + localStorage로 선택 상태를 표준화(아래 스펙)

---

## 2) 목표/비목표

### 목표(Goals)
- `/mypage/strategy/`를 **Run & Results** 목적에 맞게 단순화
- 아래 5개 목적을 각각 단일 페이지로 제공
  1) 전략 목록관리(생성/삭제/목록) → `/mypage/strategy/manage` (**확정**)
  2) 전략 운영(start/pause/stop/execute/scheduler)
  3) 전략 수정(PATCH + Config PATCH)
  4) Symbol States 조회
  5) Signals + Statistics 조회
- `static/js/pages/strategy.js`의 기능을 **페이지 단위 JS 파일**로 분리해 책임을 명확히 함
- 사이드바 네비에 신규 페이지 링크를 추가하여 이동 비용을 낮춤

### 비목표(Non-Goals)
- API 스펙 변경/추가 (이번 작업은 페이지 분리/리팩토링이 목표)
- 도메인 로직/서비스 레이어 리팩토링
- UI 디자인 대규모 개편(기능 분리 위주)

---

## 3) IA / URL 매핑(최종안)

### 최종 URL
- Run & Results(스크리닝/결과/히스토리): **`/mypage/strategy/`**
- 전략 목록관리(생성/삭제/목록): **`/mypage/strategy/manage`** ✅ (확정/SSOT)
- 전략 운영(start/pause/stop/execute/scheduler): `/mypage/strategy/operate`
- 전략 수정(PATCH + Config PATCH): `/mypage/strategy/edit`
- Symbol States 조회: `/mypage/strategy/symbol-states`
- Signals + Statistics 조회: `/mypage/strategy/signals`

### 공통 규칙(선택된 전략 컨텍스트)
- `/mypage/strategy/manage`를 제외한 4개 관리성 페이지(operate/edit/symbol-states/signals)는 기본적으로 `strategy_id`가 필요
- 컨텍스트 전달 방식(Decision):
  - 1순위: query param `?strategy_id=<id>`
  - 2순위(보조): localStorage `strategy.selected.v1`
  - 페이지 진입 시: `query param → localStorage` 순으로 결정

Decision / Rationale / Alternatives / Risks
- Decision: query param + localStorage 병행
- Rationale: 북마크/공유 가능한 URL + 새로고침/페이지 이동에도 선택 유지
- Alternatives: path param(`/mypage/strategy/{id}/operate`)는 URL은 깔끔하지만 라우터/템플릿 분기 증가
- Risks: 오래된 localStorage가 남아 엉뚱한 전략을 대상으로 동작
  - 대응: 페이지 상단에 “현재 선택 전략 ID/Name/Status”를 항상 표시 + 위험 액션 확인(confirm)

#### (Codex 피드백 반영) `strategy_id` fail-close 규칙 (P0)
- **query param이 존재하는 경우**: `?strategy_id=`를 **단일 진실(SSOT)** 로 취급한다.
  - 숫자/형식이 잘못됐거나, `GET /api/v1/strategies/{id}` 검증에 실패(404/403 등)하면 **localStorage로 fallback 하지 않는다.**
  - 이 경우 페이지는 **safe empty state** + manage 링크만 노출하고, 운영/수정 등 위험 액션 버튼은 렌더링/동작하지 않는다.
- **query param이 없는 경우**: localStorage fallback 허용(아래 TTL/검증 통과 시)
  - localStorage 값도 `GET /api/v1/strategies/{id}`로 검증 실패 시 **즉시 clear** + empty state로 전환

#### (Codex 피드백 반영) localStorage 키/스키마 (P1)
- key: `strategy.selected.v1`
- value 예시:
  - `{ "id": 123, "account_no": "12345678", "updated_at": 1760000000 }`
- TTL: `updated_at` 기준 **24시간**(초과 시 무효 처리 + clear)
- 멀티탭/다중 계좌 충돌 최소화:
  - 가능하면 key를 `strategy.selected.v1.{account_no}` 형태로 확장(선택)
  - 모든 페이지 상단에 “현재 선택 전략”을 항상 표시해 사용자 확인 비용을 낮춘다.

#### (Codex 피드백 반영) Output Panel 렌더링 규칙 (P1)
- 응답/에러 원문 출력은 **반드시 `textContent`(또는 `<pre>`에 plain text)** 로만 렌더링한다.
- `innerHTML` 금지(응답 문자열이 HTML로 해석되어 XSS가 될 수 있음)

---

## 4) 페이지별 상세 스펙(가장 중요)

> 표기 규칙
> - Toast: 사용자에게 즉시 보이는 상단/우하단 알림(성공/실패)
> - Output Panel: JSON/에러 로그를 보여주는 `<pre>` 영역
> - 기존 소스 매핑: `static/js/pages/strategy.js` 내 **함수명 기준**으로 이동 대상을 명시


### 4.1 `/mypage/strategy/` — Run & Results (단순화 대상)

#### 목적(1줄)
- **스크리닝 실행**(GC/MA5) + **결과 확인** + **관심 종목 히스토리 추적**

#### UI 섹션(heading 단위)
1) 전략 선택 탭
   - 탭: 골든크로스 / MA5 돌파
2) (GC) 종목 스크리닝
   - 스캔 실행/재무필터/유니버스 스캔/유니버스 갱신
   - 마지막 검색 라벨(캐시/신선도 표시)
   - 통계 카드(전체/GC/눌림목/매수 관심/매수 적기/보유 중)
   - 결과 테이블 + 탭 필터(매수대상/매수적기/매수관심/재무통과/턴어라운드/전체)
3) 관심 종목 히스토리
   - 활성 종목 갱신
   - 마지막 갱신 라벨
   - 히스토리 테이블(활성 토글/삭제)
4) (MA5) MA5 돌파 스크리닝
   - 스캔/직접입력 스캔
   - 마지막 검색 라벨
   - 통계 카드 + 결과 테이블 + 탭 필터

#### 입력/필터(기본값)
- GC
  - `stoch_threshold` 기본 30
  - `gc_only` 기본 true
  - (현 HTML 기준) `include_etf`는 노출하지 않음 (필요 시 추후 복원)
- MA5
  - `short_period` 기본 5
  - `long_period` 기본 300
  - `envelope_pct` 기본 0.7
  - `use_volume_filter` 기본 true
- Signals/States/Strategy CRUD 관련 입력은 **이 페이지에서 제거**

#### 버튼/액션(성공/실패 토스트 문구)
- GC 스캔
  - 성공: `골든크로스 스캔 완료: {n}개 종목`
  - 실패: `골든크로스 스캔 실패: {reason}`
- 재무 필터
  - 성공: `재무 필터 완료: 통과 {pass} / 턴어라운드 {turn} / 미통과 {fail}`
  - 실패: `재무 필터 실패: {reason}`
- 유니버스 스캔
  - 성공: `유니버스 조회 완료: {total}개`
  - 실패: `유니버스 조회 실패: {reason}`
- 유니버스 갱신
  - 성공: `유니버스 갱신 요청 완료`
  - 실패: `유니버스 갱신 실패: {reason}`
- 히스토리 갱신
  - 성공: `활성 종목 갱신 완료: {updated_count}개`
  - 실패: `활성 종목 갱신 실패: {reason}`
- MA5 스캔
  - 성공: `MA5 스캔 완료: {n}개 종목`
  - 실패: `MA5 스캔 실패: {reason}`

#### 결과 테이블 컬럼
- GC 스캔 테이블(현행 유지)
  - (+) 추가 버튼, 종목코드, 종목명, 기술(상태), 재무(필터상태), 현재가, MA Gap, Stoch K/D, 매출YoY, 영업이익률
- 히스토리 테이블(현행 유지)
  - (활성 토글), 종목코드, 종목명, 상태, 현재가, MA Gap, Stoch K, Stoch D, 분석시간, 삭제
- MA5 스캔 테이블(현행 유지)
  - 종목코드, 종목명, 상태, 현재가, MA5, MA300, 상단가, 괴리율, 거래량비

#### empty/loading/error state
- 스캔 전: “버튼을 클릭하세요” 또는 placeholder message
- loading: 버튼 disabled + label에 `...중` 표시 + 테이블에 “결과를 불러오는 중...”
- error: Toast + Output Panel에 원문 JSON/문자열 저장
- 캐시(stale) 로드 시: last-search 라벨에 `cached/stale` 스타일 적용

#### 기존 `static/js/pages/strategy.js` 기능 이동(소스 기준 매핑)
- **남는다(= 이 페이지 유지)**
  - 전략 탭: `showStrategy`
  - GC 스크리닝: `scanGoldenCross`, `applyFinancialFilter`, `displayGcScanResults`, `renderGcScanTable`, `showGcTab`, `getGcStateClass/Label`, `getFinStatusClass/Label`
  - 유니버스: `scanStocks`, `refreshUniverse`, `displayUniverseStocks`, `renderUniverseTable`, `showUniverseTab`
  - MA5 스크리닝: `scanMA5Breakout`, `scanMA5Symbols`, `displayMA5ScanResults`, `renderMA5ScanTable`, `showMA5Tab`, `getMA5StateClass/Label`
  - 히스토리: `loadBuyHistory`, `addToHistory`, `deleteBuyHistory`, `toggleBuyActive`, `refreshBuyHistory`, `renderBuyHistoryTable`
  - 캐시/쿨다운/라벨: `canScan`, `saveLastScan/loadLastScan`, `updateLastSearchLabel`, `canRefresh`, `saveLastRefresh/loadLastRefresh`, `updateLastRefreshLabel`, `loadSavedScans`
- **제거(다른 페이지로 이동)**
  - 전략 목록/관리: `loadStrategies`, `createStrategy`, `deleteStrategy`, `selectStrategy`, `renderStrategyList`
  - 전략 운영: `startStrategy/pauseStrategy/stopStrategy/executeStrategy/getSchedulerStatus` 및 관련 util
  - 전략 수정: `patchStrategy`, `getStrategyConfig`, `patchStrategyConfig`, `fillStrategyPatchForm`...
  - Symbol States: `loadSymbolStates`, `renderSymbolStatesTable`
  - Signals/Statistics: `loadSignals`, `renderSignalsTable`, `loadSignalStatistics`


---

### 4.2 `/mypage/strategy/manage` — 전략 목록관리(생성/삭제/목록)

#### 목적(1줄)
- 전략을 **생성/삭제/목록 조회**하고, 다른 상세 페이지로 이동하기 위한 **진입 허브**

#### UI 섹션
1) 상단: “전략 목록관리” 헤더 + 설명
2) 필터/조회
   - 새로고침 버튼
   - (선택) account_no, status_filter 입력 (API가 지원하므로 UI 제공 여부 결정)
3) 전략 생성 폼
   - name, strategy_type, account_no(선택), symbols(csv)
4) 전략 목록 테이블
   - 각 row에 “상세 보기(선택)”, “삭제” 버튼
   - 각 row에 “운영/수정/상태/신호”로 이동 링크(= 페이지 네비)
5) Output Panel
   - 선택한 전략 상세 JSON

#### 입력/필터(기본값)
- create
  - strategy_type 기본 `golden_cross`
  - symbols: CSV 입력(공백 trim)
- list filter(옵션)
  - account_no: empty → 전체
  - status_filter: empty → 전체

Decision (Codex 피드백 반영)
- manage의 list filter는 **기본 UI에는 숨기고**, “고급 필터(접기/펼치기)”로 제공한다.
  - 이유: 기본 동선은 단순 목록/선택이므로 UI 과밀 방지
  - 그래도 운영 환경에서 계좌/상태로 목록이 커질 수 있어 옵션은 유지

#### 버튼/액션(+ 토스트)
- 전략 목록 새로고침
  - 성공: `전략 목록 로드 완료: {n}개`
  - 실패: `전략 목록 로드 실패: {reason}`
- Create
  - 성공: `전략 생성 완료: ID={id}`
  - 실패: `전략 생성 실패: {reason}`
- Delete
  - confirm: `전략 {id}를 삭제할까?` (현행 유지 가능)
  - 성공: `전략 삭제 완료: ID={id}`
  - 실패: `전략 삭제 실패: {reason}`
- Select(row click or Select button)
  - 성공: `전략 선택: ID={id}` (토스트는 선택 사항)
  - 실패: `전략 상세 조회 실패: {reason}`

#### 결과 테이블 컬럼
- ID / Name / Type / Status / Symbols / Actions
- Actions(정의)
  - Select
  - Delete
  - 링크: Operate / Edit / Symbol States / Signals

#### empty/loading/error state
- empty: `전략이 없습니다.`
- loading: 테이블 placeholder `전략 목록 로딩 중...`
- error: Toast + Output Panel

#### 기존 소스 매핑(`static/js/pages/strategy.js`)
- 이동 대상(이 페이지로):
  - `loadStrategies`, `renderStrategyList`, `selectStrategy`, `createStrategy`, `deleteStrategy`, `parseSymbols`
- 공통화 후보(공통 util로):
  - `readJsonSafely`, `getStrategyFromResponse`, `updateSelectedStrategyLabel`

Decision / Rationale / Alternatives / Risks
- Decision: manage 페이지는 CRUD만 (start/stop 등 운영 액션은 제거)
- Rationale: 오조작 리스크 감소 + 정보 구조 명확화
- Alternatives: row actions로 start/stop 유지(현행) — 빠르지만 페이지 목적이 흐려짐
- Risks: 자주 쓰던 start/stop이 한 번 더 클릭 필요


---

### 4.3 `/mypage/strategy/operate` — 전략 운영(start/pause/stop/execute/scheduler)

#### 목적(1줄)
- 선택된 전략을 **운영(상태전환/수동 실행/스케줄러 확인)**

#### UI 섹션
1) 상단: 현재 선택 전략 표시
   - strategy_id, name, status (가능하면 GET /strategies/{id}로 표시)
2) 운영 버튼 그룹
   - Start / Pause / Stop / Execute
   - Execute 옵션: `dry_run`(default true), `force`(default false)
3) Scheduler Status
   - 조회 버튼 + 결과 출력
4) Output Panel
   - 각 액션 결과 JSON

#### 입력/필터(기본값)
- `strategy_id`: query/localStorage에서 로드
- execute params
  - `dry_run=true`
  - `force=false`

#### (Codex 피드백 반영) 안전 가드/보호 규칙 (P0)
- **In-flight 중복 클릭 차단**: 요청 진행 중에는 관련 버튼을 disabled 처리하고, 완료/실패 시 반드시 해제한다.
- **상태 전이 가드(버튼 enable matrix)**: `GET /api/v1/strategies/{id}`의 `status`를 기준으로 허용되지 않는 버튼은 disabled 한다.
  - 예시(상태명이 다르면 동치 매핑):
    - RUNNING: Start 비활성, Pause/Stop/Execute 활성(Execute는 추가 보호 적용)
    - PAUSED: Pause 비활성, Start/Stop/Execute 활성
    - STOPPED: Stop 비활성, Start/Execute 활성
- **Execute 보호**:
  - Execute는 항상 confirm을 거친다(전략 ID/Name/옵션 표시).
  - `dry_run=false`인 경우: **2단 확인**(예: “위험 실행 동의” 체크 + 재확인 confirm/문구 입력)을 필수로 둔다.
- **`strategy_id` 불명/검증 실패 시 fail-close**: 버튼 그룹 자체를 노출하지 않거나 모두 disabled + 안내만 표시한다.

#### 버튼/액션(+ 토스트)
- Start
  - 성공: `전략 시작 완료: ID={id}`
  - 실패: `전략 시작 실패: {reason}`
- Pause
  - 성공: `전략 일시정지 완료: ID={id}`
  - 실패: `전략 일시정지 실패: {reason}`
- Stop
  - confirm: `전략을 중지할까? (ID={id})`
  - 성공: `전략 중지 완료: ID={id}`
  - 실패: `전략 중지 실패: {reason}`
- Execute
  - confirm(필수): `전략을 실행할까? (dry_run={dry_run})`
  - 성공: `전략 실행 완료: ID={id}`
  - 실패: `전략 실행 실패: {reason}`
- Scheduler Status
  - 성공: `스케줄러 상태 조회 완료`
  - 실패: `스케줄러 상태 조회 실패: {reason}`

#### 결과 테이블 컬럼
- (필수 아님) execute 결과에 trades/signals가 포함되면 간단 테이블로 렌더링(추가 스코프)

#### empty/loading/error state
- strategy_id 없음: `전략을 선택하세요 → (링크) /mypage/strategy/manage`
- loading: 버튼 disabled + Output Panel `...중`
- error: Toast + Output Panel

#### 기존 소스 매핑(`static/js/pages/strategy.js`)
- 이동 대상(이 페이지로):
  - `getControlStrategyId`, `getSelectedStrategyId`, `setControlOutput`, `callStrategyAction`
  - `startStrategy`, `pauseStrategy`, `stopStrategy`, `executeStrategy`, `getSchedulerStatus`

---

### 4.4 `/mypage/strategy/edit` — 전략 수정(PATCH + Config PATCH)

#### 목적(1줄)
- 전략 메타/심볼 및 전략 Config를 안전하게 수정

#### UI 섹션
1) 상단: 현재 선택 전략 표시 + “상세 새로고침”
2) 전략 PATCH 폼
   - name, status, description, symbols(csv)
3) Config (GET/PATCH)
   - GET Config → textarea에 pretty JSON
   - PATCH Config → textarea JSON을 payload로 전송
4) Output Panel
   - PATCH/GET 결과 JSON

#### 입력/필터(기본값)
- PATCH
  - 빈 값은 “변경 안 함”으로 처리
  - (Codex 피드백 반영) **clear/null 정책**: 값 제거가 필요한 필드(description 등)는
    - 별도 “비우기(=null로 설정)” 체크박스/토글을 둔다(빈 문자열 입력과 구분).
    - 또는 입력값으로 `null`(문자열) 같은 센티넬을 허용하지 않고, UI에서 명시적으로 처리한다.
- Config
  - textarea가 비면 PATCH 불가

#### 버튼/액션(+ 토스트)
- 상세 새로고침
  - 성공: `전략 상세 로드 완료: ID={id}`
  - 실패: `전략 상세 로드 실패: {reason}`
- PATCH(전략)
  - 성공: `전략 수정 완료: ID={id}`
  - 실패: `전략 수정 실패: {reason}`
- GET Config
  - 성공: `Config 조회 완료: ID={id}`
  - 실패: `Config 조회 실패: {reason}`
- PATCH Config
  - 성공: `Config 수정 완료: ID={id}`
  - 실패: `Config 수정 실패: {reason}`

#### 결과 테이블 컬럼
- 없음(주로 JSON 출력)

#### empty/loading/error state
- strategy_id 없음: manage로 유도
- JSON 파싱 실패: toast `JSON 파싱 오류: ...` + textarea 유지

#### 기존 소스 매핑
- 이동 대상(이 페이지로):
  - `fillStrategyPatchForm`, `resetStrategyPatchForm`, `loadSelectedStrategyDetail`, `patchStrategy`
  - `getStrategyConfig`, `patchStrategyConfig`

---

### 4.5 `/mypage/strategy/symbol-states` — Symbol States 조회

#### 목적(1줄)
- 전략별 종목 상태머신(Symbol States)을 빠르게 조회/필터링

#### UI 섹션
1) 상단: 현재 선택 전략 표시
2) 조회/필터
   - Load 버튼
   - (선택) state 필터 dropdown: ALL/WAITING_FOR_GC/WAITING_FOR_PULLBACK/READY_TO_BUY/IN_POSITION
3) 결과 테이블
4) Output Panel(JSON)

#### 입력/필터(기본값)
- limit/offset은 현재 API 없음 → UI 제공하지 않음

#### 버튼/액션(+ 토스트)
- Load
  - 성공: `Symbol States 조회 완료: {n}개`
  - 실패: `Symbol States 조회 실패: {reason}`

#### 결과 테이블 컬럼(현행 유지 + 확장 가능)
- 심볼 / 상태 / 최근 종가 / 미실현 수익률

#### empty/loading/error state
- empty: `결과가 없습니다.`

#### 기존 소스 매핑
- 이동 대상(이 페이지로): `loadSymbolStates`, `renderSymbolStatesTable`

---

### 4.6 `/mypage/strategy/signals` — Signals + Statistics 조회

#### 목적(1줄)
- 전략별 Signals 이력과 Statistics를 분리된 화면에서 조회

#### UI 섹션
1) 상단: 현재 선택 전략 표시
2) Signals 조회
   - limit / offset 입력
   - Load 버튼
   - 결과 테이블
3) Statistics 조회
   - (선택) days 입력(기본 30)
   - Load Statistics 버튼
   - 결과 출력(pre)

#### 입력/필터(기본값)
- limit=50, offset=0
- days=30

#### 버튼/액션(+ 토스트)
- Load Signals
  - 성공: `Signals 조회 완료: {n}개`
  - 실패: `Signals 조회 실패: {reason}`
- Load Statistics
  - 성공: `Statistics 조회 완료`
  - 실패: `Statistics 조회 실패: {reason}`

#### 결과 테이블 컬럼(현행 유지)
- 시간 / 심볼 / 유형 / 상태 / 시그널가 / 목표/체결 수량

#### empty/loading/error state
- empty: `결과가 없습니다.`

#### 기존 소스 매핑
- 이동 대상(이 페이지로): `loadSignals`, `renderSignalsTable`, `loadSignalStatistics`

---

## 5) API 호출 매핑(페이지/버튼 → endpoint + payload)

### `/mypage/strategy/` (Run & Results)
- [GC] 골든크로스 스캔
  - `GET /api/v1/strategies/universe/golden-cross-scan?stoch_threshold={float}&gc_only={bool}&market={optional}`
  - payload: 없음
- [GC] 재무 필터
  - `POST /api/v1/strategies/universe/financial-filter?target_states=OPTIMAL_BUY&target_states=BUY_INTEREST&target_states=READY_TO_BUY`
  - body: `GoldenCrossScanListDTO` 형태(현행: JS가 scanResult wrapper 구성)
- [Universe] 전체 종목 스캔
  - `GET /api/v1/strategies/universe?eligible_only=true` (+ market optional)
- [Universe] 유니버스 갱신
  - `POST /api/v1/strategies/universe/refresh`
  - body: `{}`
- [MA5] 유니버스 MA5 돌파 스캔
  - `GET /api/v1/strategies/universe/ma5-breakout-scan?short_period={int}&long_period={int}&envelope_pct={float}&use_volume_filter={bool}`
- [MA5] 특정 심볼 스캔
  - `POST /api/v1/strategies/universe/ma5-breakout-scan-symbols?...(same query)`
  - body: `[{symbol,name,market}, ...]`
- [History] 목록
  - `GET /api/v1/strategies/analysis-history?analysis_type=buy&limit=50`
- [History] 추가
  - `POST /api/v1/strategies/analysis-history`
  - body: `AnalysisHistoryCreateDTO` (현행 addToHistory payload)
- [History] 삭제
  - `DELETE /api/v1/strategies/analysis-history/{id}`
- [History] 활성 토글
  - `PATCH /api/v1/strategies/analysis-history/{id}/active?is_active={bool}`
- [History] 일괄 갱신
  - `POST /api/v1/strategies/analysis-history/refresh?analysis_type=buy`

### `/mypage/strategy/manage`
- 목록
  - `GET /api/v1/strategies?account_no={optional}&status_filter={optional}`
- 생성
  - `POST /api/v1/strategies`
  - body: `{ name, strategy_type, account_no|null, symbols:[...] }`
- 상세
  - `GET /api/v1/strategies/{strategy_id}`
- 삭제
  - `DELETE /api/v1/strategies/{strategy_id}`

### `/mypage/strategy/operate`
- start/pause/stop
  - `POST /api/v1/strategies/{strategy_id}/start`
  - `POST /api/v1/strategies/{strategy_id}/pause`
  - `POST /api/v1/strategies/{strategy_id}/stop`
- execute
  - `POST /api/v1/strategies/{strategy_id}/execute`
  - body: `{ dry_run: true, force: false }` (DTO에 맞춰 조정)
- scheduler status
  - `GET /api/v1/strategies/scheduler/status`

### `/mypage/strategy/edit`
- patch strategy
  - `PATCH /api/v1/strategies/{strategy_id}`
  - body: 부분 업데이트 payload
- get/patch config
  - `GET /api/v1/strategies/{strategy_id}/config`
  - `PATCH /api/v1/strategies/{strategy_id}/config` body: `GoldenCrossConfigDTO`

### `/mypage/strategy/symbol-states`
- `GET /api/v1/strategies/{strategy_id}/symbol-states`

### `/mypage/strategy/signals`
- list
  - `GET /api/v1/strategies/{strategy_id}/signals?limit={int}&offset={int}`
- statistics
  - `GET /api/v1/strategies/{strategy_id}/signals/statistics?days={int}`

---

## 6) 프론트(템플릿/JS/CSS) 구조 변경안(파일 단위)

### 템플릿
- 유지/수정
  - `templates/page/strategy.html`
    - Decision: **Run & Results만 남기고** 관리/운영/수정/조회 섹션 제거
- 신규 생성
  - `templates/page/strategy_manage.html`
  - `templates/page/strategy_operate.html`
  - `templates/page/strategy_edit.html`
  - `templates/page/strategy_symbol_states.html`
  - `templates/page/strategy_signals.html`

각 템플릿 공통
- `{% extends "layouts/base.html" %}`
- `{% block extra_css_links %}`에 `strategy.css` 포함
- `{% block extra_script_tags %}`에 페이지 전용 JS만 include

### JS
- 기존
  - `static/js/pages/strategy.js` (현재: 모든 기능이 한 파일)
- 변경안(권장)
  - `static/js/pages/strategy.js` → **run 전용**으로 축소
  - 신규
    - `static/js/pages/strategy_manage.js`
    - `static/js/pages/strategy_operate.js`
    - `static/js/pages/strategy_edit.js`
    - `static/js/pages/strategy_symbol_states.js`
    - `static/js/pages/strategy_signals.js`
    - `static/js/pages/strategy_shared.js` (공통 util)
      - query/localStorage에서 strategy_id 로딩
      - `readJsonSafely`, `showToast`, `formatNumber/Time` 등

Decision / Rationale / Alternatives / Risks
- Decision: “페이지당 1 JS” + shared util
- Rationale: 책임/번들 크기/DOM 의존성을 줄이고 변경 범위를 한정
- Alternatives: ES module import 체계 도입(번들러 필요)
- Risks: 공통 util 중복/전역 함수 충돌
  - 대응: `window.*` export 최소화 + 페이지별로 필요한 함수만 노출

### CSS
- 기본: `static/styles/strategy.css`를 모든 전략 관련 페이지에서 재사용
- 필요 시 추가
  - `static/styles/toast.css` (또는 `mypage.css`에 통합)
  - Toast DOM은 `layouts/base.html`에 공통 삽입하는 방식도 가능

---

## 7) 백엔드(page routers) 변경안

대상 파일
- `src/application/interface/page/strategy_page_router.py`

변경안
- 기존
  - `GET /mypage/strategy/` → `page/strategy.html`
- 신규 라우트 추가(동일 prefix 유지)
  - `GET /mypage/strategy/manage` → `page/strategy_manage.html`
  - `GET /mypage/strategy/operate` → `page/strategy_operate.html`
  - `GET /mypage/strategy/edit` → `page/strategy_edit.html`
  - `GET /mypage/strategy/symbol-states` → `page/strategy_symbol_states.html`
  - `GET /mypage/strategy/signals` → `page/strategy_signals.html`

active_page 제안(사이드바 하이라이트용)
- `/mypage/strategy/` → `strategy_run`
- `/mypage/strategy/manage` → `strategy_manage`
- `/mypage/strategy/operate` → `strategy_operate`
- `/mypage/strategy/edit` → `strategy_edit`
- `/mypage/strategy/symbol-states` → `strategy_symbol_states`
- `/mypage/strategy/signals` → `strategy_signals`

Risks
- 동일 prefix에서 경로가 늘어나면 라우터 유지보수 이슈
  - 대응: strategy_page_router 내에서 핸들러를 페이지별 함수로 분리하거나, 파일 자체를 2~3개로 분할(차후)

---

## 8) 사이드바/네비 변경안(`templates/layouts/_sidebar.html`)

### 변경 목표
- 사용자가 “Run”과 “관리”를 명확히 구분해 이동

### 제안 IA
- Strategy 섹션 아래에 링크 추가
  - Buy Strategy (Run) → `/mypage/strategy/`
  - 전략 목록관리 → `/mypage/strategy/manage`
  - 전략 운영 → `/mypage/strategy/operate`
  - 전략 수정 → `/mypage/strategy/edit`
  - Symbol States → `/mypage/strategy/symbol-states`
  - Signals/Statistics → `/mypage/strategy/signals`

### active 처리
- 기존: `active_page == 'strategy'` 단일
- 변경: 위 7)에서 제안한 `active_page` 값으로 각 메뉴 active 처리

Alternatives
- 사이드바는 2개만 유지(Run/Manage)하고, 나머지는 manage 내부에서 버튼/링크 제공

Risks
- 사이드바가 길어짐
  - 대응: “Strategy” 섹션 내부에서 순서 정리(Run → Manage → Operate → Edit → States → Signals)

---

## 9) 테스트/검증 플랜(수동 체크리스트)

1) `/mypage/strategy/` 접속 시 전략 관리 섹션(목록/운영/수정/상태/신호)이 **노출되지 않는지**
2) `/mypage/strategy/`에서 GC 스캔이 정상 동작하고 결과 테이블이 렌더링되는지
3) GC 탭 필터(매수대상/매수적기/재무통과 등) 클릭 시 필터링이 정상인지
4) GC 재무 필터 버튼이 스캔 결과 없을 때 경고 처리되는지
5) 유니버스 스캔/갱신이 정상 동작하는지
6) buy history 로딩/추가/삭제/활성 토글이 정상인지
7) buy history 갱신 쿨다운/라벨 표시가 정상인지
8) MA5 스캔/직접입력 스캔이 정상 동작하는지
9) MA5 탭 필터(BREAKOUT/ABOVE/all)가 정상인지
10) 캐시된 결과(stale) 표시가 정상인지(새로고침/재접속 포함)
11) `/mypage/strategy/manage`에서 전략 목록 로드가 정상인지
12) manage에서 전략 생성이 정상이고, 생성 후 목록에 나타나는지
13) manage에서 전략 삭제가 정상이고, 삭제 후 목록에서 사라지는지
14) manage에서 row 선택 시 상세 JSON이 출력되고, 선택 전략이 저장되는지(localStorage)
15) operate/edit/states/signals 페이지에서 `strategy_id` 미지정 시 안내 문구 + manage 링크가 나오는지
16) operate에서 start/pause/stop/execute가 정상 호출되고 토스트/출력이 맞는지
17) operate에서 scheduler status가 정상 조회되는지
18) edit에서 PATCH 전략이 정상 동작하고 변경이 반영되는지
19) edit에서 Config GET/PATCH가 정상이고 textarea가 갱신되는지
20) symbol-states 페이지에서 테이블/JSON 출력이 정상인지
21) signals 페이지에서 limit/offset 적용이 정상인지
22) statistics(days) 조회가 정상인지
23) 모든 신규 페이지에서 사이드바 active 표시가 올바른지
24) 새로고침/뒤로가기 등 네비게이션에서 선택 전략 ID가 일관되게 유지되는지

---

## 10) 배포 플랜(docker compose 재빌드/다운타임/롤백)

### 배포 절차(예상)
1) 변경 사항은 템플릿/정적 파일/페이지 라우터 수준이므로 DB 마이그레이션 없음
2) docker compose 재빌드 & 재기동
   - `docker compose build --no-cache` (필요 시)
   - `docker compose up -d`
3) 배포 후 스모크 테스트: 9) 체크리스트 중 1,2,11,16을 우선 수행

### 다운타임
- 정적 파일/템플릿/라우터 변경이므로 재기동 시간만큼 짧은 다운타임 예상

### 롤백
- 직전 커밋으로 revert 후 동일 재빌드/재기동

Risks
- 브라우저 캐시로 구 JS가 남아 동작 불일치
  - 대응: 파일명 버전닝(예: `strategy_manage.v1.js`) 또는 캐시 무효화 헤더(추후)

Decision (Codex 피드백 반영)
- 템플릿에서 JS/CSS include 시 **캐시 버스팅 파라미터를 SSOT로 확정**한다.
  - 예: `<script src="/static/js/pages/strategy_manage.js?v={{ static_version }}"></script>`
  - `static_version`은 (1) env/설정 값, (2) build timestamp, (3) git sha 중 하나로 주입한다(프로젝트 관례에 맞게 선택).

---

## 11) 수용기준(AC) 체크리스트 (v1.0 / 20개)

> NOTE: Codex 피드백 반영 후 **최종 AC는 문서 하단 `13) 최종 AC` 섹션(v1.1)** 을 기준으로 한다.

1) `/mypage/strategy/`에 전략 목록/운영/수정/상태/신호 UI가 존재하지 않는다.
2) `/mypage/strategy/`에서 GC 스캔 버튼 클릭 시 API 호출이 발생한다.
3) GC 스캔 성공 시 결과 테이블이 1행 이상 렌더링되거나, “결과 없음” empty state가 렌더링된다.
4) GC 스캔 실패 시 toast로 실패 메시지가 표시되고 Output Panel에 원문이 기록된다.
5) 재무 필터는 GC 스캔 결과가 없으면 실행되지 않고 안내 메시지를 보여준다.
6) 재무 필터 성공 시 PASS/FAIL/TURNAROUND 통계가 화면에 표시된다.
7) 유니버스 갱신은 성공/실패 토스트가 있다.
8) buy history는 페이지 로드 시 자동 조회된다.
9) buy history “활성 토글”은 즉시 UI에 반영된다.
10) buy history “삭제”는 confirm을 거치며 삭제 후 목록이 즉시 반영된다.
11) MA5 스캔 성공 시 통계 카드가 표시된다.
12) `/mypage/strategy/manage`에서 전략 목록을 조회할 수 있다.
13) manage에서 전략 생성 시 필수값(name/symbols) 검증이 있다.
14) manage에서 전략 삭제가 가능하다.
15) operate/edit/symbol-states/signals 페이지는 strategy_id가 없으면 안전한 empty state로만 표시된다(운영 버튼 노출/동작 금지).
16) operate에서 start/pause/stop 호출이 각각 올바른 endpoint로 전송된다.
17) operate에서 execute는 dry_run 기본 true이며, 사용자가 변경 가능하다.
18) edit에서 PATCH 전략은 변경된 필드만 payload로 전송한다.
19) edit에서 Config PATCH는 textarea JSON 파싱 실패 시 요청을 보내지 않는다.
20) 사이드바에 신규 메뉴가 추가되고 각 페이지에서 active 표시가 정확하다.

---

## Step3(Codex 리뷰)용 Self-check 질문/체크리스트

1) `/mypage/strategy/`에서 제거해야 할 섹션이 남아있지 않은가? (DOM id 기준으로 확인)
2) JS 분리 후 각 페이지가 **필요한 JS만** 로드하는가? (불필요한 `window.*` export 제거)
3) `strategy_id` 해석 우선순위가 문서대로 구현됐는가? (query → localStorage)
4) operate/edit 페이지에서 `strategy_id` 없을 때 **위험 액션이 실행될 수 있는 경로가 0개**인가?
5) 기존 `static/js/pages/strategy.js`에서 함수 이동 시, 이벤트 핸들러(onclick)가 새 파일 함수명을 정확히 참조하는가?
6) API endpoint/메서드가 정확한가? (특히 `POST /start|pause|stop`, `POST /execute`, `PATCH /config`)
7) 실패 케이스에서 UI가 멈추지 않고(loading 해제), toast + output이 남는가?
8) 캐시(localStorage) 스키마 버전 변경/호환이 깨지지 않는가?
9) 새 템플릿에서 `strategy.css` 포함 및 base layout extend가 일관적인가?
10) 사이드바 active_page 값이 백엔드에서 일관되게 내려오는가?


---

## 12) Codex 리뷰 피드백 반영 (v1.1)

| # | Codex 피드백(요약) | 우선순위 | 반영 내용(결정/스펙) |
|---:|---|:---:|---|
| 1 | `strategy_id` 해석에서 query 무효 시 localStorage fallback 위험 | P0 | 섹션 3에 **fail-close 규칙** 추가: query가 있으면 SSOT로 취급하고 검증 실패 시 fallback 금지 + safe empty state |
| 2 | execute 보호 약함(특히 `dry_run=false`) | P0 | 섹션 4.3에 **Execute 2단 확인**(체크+재확인/문구 입력) 명시 |
| 3 | 상태 전이 가드/중복 실행 차단(버튼 disable) 누락 | P0 | 섹션 4.3에 **status 기반 enable matrix** + in-flight disable 규칙 추가 |
| 4 | localStorage 단일 키 오염/멀티탭 충돌 | P1 | 섹션 3에 **`strategy.selected.v1` 스키마 + TTL(24h)** + 계좌별 키 확장 옵션 추가 |
| 5 | Output Panel 원문 출력 방식(XSS) | P1 | 섹션 3에 **textContent-only** 규칙 추가(=innerHTML 금지) |
| 6 | manage filter UI 제공 여부 미결정 | P1 | 섹션 4.2에 **고급 필터(접기/펼치기)로 제공**으로 확정 |
| 7 | edit PATCH의 “빈 값=변경 안 함” vs clear 요구 충돌 | P1 | 섹션 4.4에 **clear/null 정책**(명시적 체크박스) 추가 |
| 8 | manage→다른 페이지 링크의 query/localStorage 규칙 불명확 | P1 | 섹션 3에 query SSOT + localStorage 보조(검증/TTL)로 명시 |
| 9 | 캐시버스팅이 예시 수준 | P1 | 섹션 10에 **`?v={{ static_version }}` 방식 SSOT** 추가 |



## 13) 최종 AC(수용 기준) 체크리스트 (v1.1)

### A. 공통/컨텍스트/안전
- [ ] (AC01) `/mypage/strategy/manage`가 전략 선택의 SSOT 허브이며, 다른 페이지는 manage로 돌아갈 수 있는 링크를 제공한다.
- [ ] (AC02) operate/edit/symbol-states/signals는 **유효한 `strategy_id`가 없으면** safe empty state만 표시하고, 위험 액션은 노출/동작하지 않는다.
- [ ] (AC03) query param `strategy_id`가 **존재하지만 무효/검증 실패**하면 localStorage로 fallback 하지 않는다(fail-close).
- [ ] (AC04) query param이 없을 때만 localStorage를 보조로 사용하며, TTL(24h) 초과 또는 검증 실패 시 clear 된다.
- [ ] (AC05) Output Panel은 `innerHTML`을 사용하지 않고 text 기반(`textContent`/`<pre>`)으로만 렌더링한다.

### B. Run & Results (`/mypage/strategy/`)
- [ ] (AC06) `/mypage/strategy/`에 전략 목록/운영/수정/상태/신호 UI가 존재하지 않는다.
- [ ] (AC07) GC/MA5 스캔 및 결과 테이블/empty state가 정상 렌더링된다(기존 기능 유지).

### C. Manage (`/mypage/strategy/manage`)
- [ ] (AC08) 전략 목록 조회/생성/삭제가 가능하다.
- [ ] (AC09) 목록이 커질 때를 대비해 account_no/status_filter는 “고급 필터”로 제공된다(기본 UI 과밀 방지).
- [ ] (AC10) 다른 페이지로 이동하는 링크는 항상 `?strategy_id=`를 포함한다(북마크/공유 가능한 URL).

### D. Operate (`/mypage/strategy/operate`)
- [ ] (AC11) start/pause/stop/execute/scheduler-status가 올바른 endpoint로 호출된다.
- [ ] (AC12) in-flight 중에는 중복 클릭이 차단되고, 완료/실패 후 버튼이 정상 복구된다.
- [ ] (AC13) status 기반으로 허용되지 않는 버튼은 disabled 된다(상태 전이 가드).
- [ ] (AC14) execute는 항상 confirm을 거치며, `dry_run=false`는 2단 확인(추가 동의/재확인)이 필수다.

### E. Edit / States / Signals
- [ ] (AC15) edit에서 PATCH 전략은 변경 필드만 전송하며, 값 제거(clear)는 별도 “비우기” UI로만 수행된다.
- [ ] (AC16) symbol-states/signals/statistics 조회가 정상 동작하고 empty/loading/error state가 있다.

### F. 네비/캐시
- [ ] (AC17) 사이드바에 신규 메뉴가 추가되고 각 페이지에서 active 표시가 정확하다.
- [ ] (AC18) JS/CSS include에는 `?v={{ static_version }}`(또는 동등한 방식)의 캐시 버스팅이 적용된다.

