# CLAUDE.md - KIS Trading API Service

> **증권 자동매매 서비스**의 프로젝트 개요 및 진입점 문서

## 📋 프로젝트 개요

### 🎯 시스템 목적
한국투자증권 Open API를 활용한 **엔터프라이즈급 자동매매 시스템** 구축

### 📈 프로젝트 구성
1. **현재 상태: 샘플 코드 기반** - 166개 API 샘플 코드 제공 (REST 126개, WebSocket 40개)
2. **목표: FastAPI 서버 구축** - 헥사고날 아키텍처 기반 자동매매 API 서버

### 서비스 정보
- **서비스명**: KIS Trading API Service
- **포트**: 8000 (개발), 8080 (운영)
- **역할**: 한국투자증권 Open API 기반 자동매매 서비스
- **기술스택**: FastAPI, PostgreSQL, SQLAlchemy(async), Redis, WebSocket, UV

### 주요 기능
- ✅ **다중 상품 지원** - 국내/해외 주식, 선물옵션, 채권, ETF/ETN, ELW (166개 API)
- ✅ **실전/모의투자** - 환경 분리 및 안전한 테스트
- ✅ **실시간 시세** - WebSocket 기반 40개 실시간 데이터
- ✅ **자동매매 전략** - 조건 기반 자동 주문 실행
- ✅ **계좌 관리** - 잔고, 포지션, 손익 분석
- ✅ **리스크 관리** - 손실 제한, 포지션 관리
- ✅ **대시보드** - 실시간 모니터링 및 관리
- ✅ **차트 데이터 캐싱** - PostgreSQL `ohlcv_cache` 테이블에 일봉 데이터 저장 (API 호출 최소화)

### 🆕 최근 업데이트 (2025-02)

- 백테스트 도메인에 **OHLCV DB 캐시** 도입, 장기간 데이터 재사용으로 호출량 절감
- `MarketDataService.get_chart_data`가 **기간 기반 API**(`inquire-daily-itemchartprice`)를 사용해 누락 구간을 최소화
- `BacktestService`가 실제 수집 구간을 보고하도록 개선, 트렁케이션 여부와 커버리지 비율 확인 가능
- `examples/backtest/simple_backtest.py`가 **DB 세션과 Redis 캐시**를 동시에 초기화하여 실전 실행 플로우 예시 제공
- `scripts/init_db_tables.py` 추가: `python scripts/init_db_tables.py`로 `ohlcv_cache` 포함 테이블 일괄 생성

---

## 🏛️ 아키텍처 개요

### 헥사고날 아키텍처 (Ports & Adapters) + 현대적 패턴

```
📁 프로젝트 구조
├── 📂 docs/                    # 프로젝트 문서
│   ├── CLAUDE.md               # 프로젝트 개요 (본 문서)
│   ├── ARCHITECTURE.md         # 아키텍처 설계
│   ├── SERVICE.md              # 서비스 구현 가이드
│   └── convention.md           # 코딩 컨벤션
│
├── 📂 examples/                # 실행 가능한 예제 모음
│   ├── examples_llm/           # LLM 연동용 API 단위 샘플
│   ├── examples_user/          # 사용자용 통합 예제
│   └── backtest/               # 백테스트 런너 및 전략 샘플
│
├── 📂 MCP/                     # MCP 서버 (Claude Desktop 연동)
│   └── Kis_Trading_MCP/        # Docker 기반 MCP 서버
│
├── 📂 scripts/                 # 운영 스크립트 (DB 초기화 등)
│   └── init_db_tables.py       # OHLCV 캐시 포함 테이블 생성
│
├── 📂 src/                     # FastAPI 서버 소스
│   ├── adapters/               # 외부 시스템 연동 (DB, Cache, KIS API 등)
│   ├── application/            # 도메인 서비스 및 유즈케이스
│   ├── settings/               # Pydantic 기반 환경 설정
│   └── main.py                 # ASGI 엔트리포인트
│
├── 📂 static/                  # 대시보드 정적 자산
├── 📂 tests/                   # 도메인 단위 Pytest 스위트
├── alembic/                    # DB 마이그레이션 스크립트
└── pyproject.toml              # 프로젝트 의존성 및 스크립트 정의
```

### 핵심 아키텍처 패턴
- **BaseRepository Pattern**: Mixin 기반 중복 제거 (40% 코드 감소)
- **통합 Service Pattern**: 복잡한 비즈니스 로직을 Service에서 통합 처리
- **@transaction 데코레이터**: 외부 호출 메서드만 적용, 내부 헬퍼는 분리
- **Session 관리 단순화**: Service layer만 session 관리
- **KIS API Client 분리**: 인증/API/WebSocket 계층 분리
- **Event-Driven**: 시세 변동, 체결 알림 등 이벤트 기반 처리
- **Async/Await**: 비동기 처리로 동시성 향상

---

## 📊 지원 금융상품 및 API 현황

### 금융상품별 API 수

| 카테고리 | API 수 | REST | WebSocket | 주요 기능 | 폴더 위치 |
|---------|--------|------|-----------|----------|----------|
| **국내주식** | 74개 | 52개 | 22개 | 현재가, 호가, 차트, 잔고, 주문, 순위분석 | `domestic_stock/` |
| **해외주식** | 34개 | 28개 | 6개 | 미국/아시아 시세, 주문, 체결, 권리종합 | `overseas_stock/` |
| **ETF/ETN** | 2개 | 2개 | 0개 | NAV 비교추이, 현재가 | `etfetn/` |

**총 166개 API 지원** (REST: 126개, WebSocket: 40개)

---

## 🚀 빠른 시작 가이드

### 1. 환경 설정

```bash
# 저장소 클론
git clone https://github.com/koreainvestment/open-trading-api.git
cd open-trading-api

# 의존성 설치 (UV 사용)
uv sync

# 설정 파일 수정
# kis_devlp.yaml 파일에 본인의 API 키 입력
```

### 2. KIS API 설정

`kis_devlp.yaml` 파일 수정:

```yaml
# 실전투자
my_app: "여기에 실전투자 앱키 입력"
my_sec: "여기에 실전투자 앱시크릿 입력"

# 모의투자
paper_app: "여기에 모의투자 앱키 입력"
paper_sec: "여기에 모의투자 앱시크릿 입력"

# 계좌번호
my_acct_stock: "증권계좌 8자리"
my_prod: "01"  # 종합계좌
```

### 3. 데이터베이스 초기화

OHLCV 캐시를 포함한 모든 테이블을 생성하려면 다음 스크립트를 실행합니다.

```bash
uv run python scripts/init_db_tables.py
```
> `.env` 또는 환경 변수에 `DATABASE_URL`이 설정되어 있어야 하며, Postgres 인스턴스가 실행 중이어야 합니다.

### 4. 샘플 코드 실행

**examples_user 방식 (통합 예제):**
```bash
cd examples/examples_user/domestic_stock

# REST API 예제
python domestic_stock_examples.py

# WebSocket 예제
python domestic_stock_examples_ws.py
```

**examples_llm 방식 (기능 단위):**
```bash
cd examples/examples_llm/domestic_stock/inquire_price

# 특정 API 테스트
python chk_inquire_price.py
```

---

## 🧠 백테스팅 데이터 파이프라인 & 캐시 전략

- **실행 흐름**: `examples/backtest/simple_backtest.py`가 Redis와 함께 비동기 DB 세션을 열고 `BacktestService`에 주입합니다.
- **캐시 우선 로드**: `BacktestDataLoader.load_ohlcv_data`는 `OHLCVRepository`를 통해 `ohlcv_cache` 테이블을 조회하고, 요청 구간이 완전히 채워져 있을 때 DataFrame을 즉시 반환합니다.
- **API 수집 개선**: 캐시 미스 시 `MarketDataService.get_chart_data`가 `inquire-daily-itemchartprice` 엔드포인트를 사용해 최대 90일 단위로 과거 데이터를 역순 탐색합니다.
- **DB 저장**: 수집된 캔들은 `save_candles_bulk`로 일괄 업서트되며, 재실행 시 중복 호출 없이 재사용됩니다.
- **데이터 품질**: 실제 수집 구간(`actual_start`, `actual_end`)과 커버리지 비율이 로그에 기록되어 KIS API 제한으로 인한 절단 여부를 확인할 수 있습니다.

---

## 🎯 도메인별 주요 API

### 1. Auth (인증)
- **토큰 발급**: `POST /oauth2/tokenP` - 접근 토큰 발급 (24시간 유효)
- **WebSocket 인증**: `POST /oauth2/Approval` - WebSocket 연결용 approval_key 발급

### 2. Order (주문)
- **국내주식 주문**: `POST /uapi/domestic-stock/v1/trading/order-cash`
- **해외주식 주문**: `POST /uapi/overseas-stock/v1/trading/order`
- **주문 취소**: `POST /uapi/domestic-stock/v1/trading/order-rvsecncl`

### 3. Account (계좌)
- **국내주식 잔고**: `GET /uapi/domestic-stock/v1/trading/inquire-balance`
- **해외주식 잔고**: `GET /uapi/overseas-stock/v1/trading/inquire-balance`
- **체결 내역**: `GET /uapi/domestic-stock/v1/trading/inquire-daily-ccld`

### 4. MarketData (시세)
- **국내주식 현재가**: `GET /uapi/domestic-stock/v1/quotations/inquire-price`
- **국내주식 호가**: `GET /uapi/domestic-stock/v1/quotations/inquire-asking-price`
- **해외주식 현재가**: `GET /uapi/overseas-price/v1/quotations/price`

### 5. WebSocket (실시간)
- **국내주식 체결**: `H0STCNT0` - 실시간 체결가
- **국내주식 호가**: `H0STASP0` - 실시간 호가
- **해외주식 체결**: `HDFSCNT0` - 해외 실시간 체결

---

## 📖 개발 가이드 문서 (계층별 분리)

| 문서 | 위치 | 담당 영역 | 언제 참고할까? |
|------|------|-----------|---------------|
| **🏠 프로젝트 개요** | [`CLAUDE.md`](./CLAUDE.md) | 전체 구조 | 프로젝트 이해, 빠른 시작 |
| **🏛️ 아키텍처** | [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 시스템 설계 | 아키텍처 이해, 계층 설계 |
| **🔧 서비스 구현** | [`SERVICE.md`](./SERVICE.md) | 비즈니스 로직 | Service/Repository 구현 |
| **📝 코딩 컨벤션** | [`convention.md`](./convention.md) | 코드 작성 규칙 | 코드 작성 시 참고 |

### 🎯 개발자별 추천 경로

#### 신규 개발자 (전체 이해)
1. **CLAUDE.md (본 문서)**: 프로젝트 전체 개요 파악
2. **ARCHITECTURE.md**: 시스템 아키텍처 이해
3. **SERVICE.md**: 도메인별 구현 방법 학습
4. **convention.md**: 코딩 규칙 숙지

#### 백엔드 개발자 (API 서버 구축)
- **ARCHITECTURE.md** → **SERVICE.md** 순으로 참고
- Service 패턴, Repository 설계, API Router 구현

#### 샘플 코드 활용자
- **examples_user/**: 실제 사용 예제 참고
- **examples_llm/**: 특정 API 기능 탐색

---

## 🛠️ 개발 환경

### 환경 요구사항
- Python 3.9+
- PostgreSQL 14+
- Redis 7+
- UV Package Manager

### 개발 명령어
```bash
# 개발 서버 실행
uvicorn src.main:app --reload --port 8000

# 데이터베이스 마이그레이션
alembic upgrade head
alembic revision --autogenerate -m "description"

# 테스트
pytest
pytest --cov=src tests/

# 코드 품질
mypy src/
black src/
isort src/
```

### 환경 변수 (.env)
```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/kis_trading

# Redis
REDIS_URL=redis://localhost:6379/0

# KIS API (실전투자)
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=12345678
KIS_PRODUCT_CODE=01

# KIS API (모의투자)
KIS_PAPER_APP_KEY=your_paper_app_key
KIS_PAPER_APP_SECRET=your_paper_app_secret
KIS_PAPER_ACCOUNT_NO=11111111
```

---

## 📚 샘플 코드 가이드

### examples_user vs examples_llm

**examples_user (사용자용 통합 예제)**
- 📁 카테고리별 폴더 구조
- 📄 통합 함수 파일: `[카테고리]_functions.py`
- 📄 실행 예제 파일: `[카테고리]_examples.py`
- 🎯 **사용 시나리오**: 실제 트레이딩 구현

**examples_llm (LLM용 기능 단위)**
- 📁 API별 개별 폴더 구조
- 📄 한줄 호출 파일: `[함수명].py`
- 📄 테스트 파일: `chk_[함수명].py`
- 🎯 **사용 시나리오**: 특정 API 기능 탐색

### 샘플 코드 예제

**REST API 호출 (examples_user):**
```python
import kis_auth as ka
from domestic_stock_functions import inquire_price

# 인증
ka.auth()

# 삼성전자 현재가 조회
result = inquire_price(
    env_dv="real",
    fid_cond_mrkt_div_code="J",
    fid_input_iscd="005930"
)
print(result)
```

**WebSocket 실시간 시세 (examples_user):**
```python
import kis_auth as ka
from domestic_stock_functions_ws import asking_price_krx

# 인증
ka.auth()
ka.auth_ws()

# WebSocket 선언
kws = ka.KISWebSocket(api_url="/tryitout")

# 삼성전자 실시간 호가 구독
kws.subscribe(request=asking_price_krx, data=["005930"])
```

**백테스트 실행 (examples/backtest):**
```bash
uv run python examples/backtest/simple_backtest.py
```
- 최초 실행 시 KIS API에서 데이터를 내려받아 `ohlcv_cache` 테이블에 적재합니다.
- 이후 동일 구간 재실행 시 DB 캐시를 사용해 호출 시간을 단축합니다.

---

## 🔧 MCP 서버 (Claude Desktop 연동)

### Docker 기반 MCP 서버
- **위치**: `MCP/Kis_Trading_MCP/`
- **기능**: Claude Desktop에서 KIS API를 MCP 프로토콜로 사용
- **지원**: 166개 API 모두 지원

### 빠른 시작
```bash
cd "MCP/Kis Trading MCP"

# Docker 이미지 빌드
docker build -t kis-trade-mcp .

# 컨테이너 실행
docker run -d \
  --name kis-trade-mcp \
  -p 3000:3000 \
  -e KIS_APP_KEY="your_app_key" \
  -e KIS_APP_SECRET="your_app_secret" \
  kis-trade-mcp

# Claude Desktop 설정
# ~/.claude_desktop_config.json
{
  "mcpServers": {
    "kis-trade-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:3000/sse"]
    }
  }
}
```

---

## 🔒 보안 및 리스크 관리

### 보안 원칙
- ✅ API 키는 환경 변수로만 관리
- ✅ 토큰은 안전한 경로에 암호화 저장
- ✅ 실전/모의 환경 완전 분리
- ✅ WebSocket 연결 시 approval_key 검증

### 리스크 관리
- ⚠️ **모의투자 우선**: 실전 투자 전 충분한 테스트
- ⚠️ **손실 제한**: 일일 손실 한도 설정
- ⚠️ **포지션 관리**: 최대 보유 종목 수 제한
- ⚠️ **긴급 정지**: 전체 주문 취소 기능

---

## 🎯 다음 개발 단계

### Phase 1: 기본 아키텍처 구축 (완료)
- [x] FastAPI 프로젝트 초기 설정
- [x] 헥사고날 아키텍처 폴더 구조 정비
- [x] BaseRepository + Mixin 패턴 구현
- [x] 의존성 주입 및 비동기 세션 관리 구성

### Phase 2: 핵심 도메인 구현 (진행 중)
- [x] MarketData Domain (기간 기반 차트 API 연동 및 Redis 캐시)
- [x] Backtest Domain (OHLCV 로더, DB 캐시, 전략 엔진 연동)
- [ ] Order Domain (주문 생성/조회)
- [ ] Account Domain (잔고/포지션)
- [ ] Auth Domain (토큰 발급/갱신)

### Phase 3: 실시간 시스템 (준비)
- [ ] WebSocket Domain (실시간 시세)
- [ ] 이벤트 핸들링 시스템
- [ ] 실시간 대시보드

### Phase 4: 자동매매 전략 (준비)
- [ ] Strategy Domain (전략 실행 고도화)
- [ ] 리스크 관리 시스템
- [ ] 실거래 연동 자동화

---

## 🔗 관련 링크

- [한국투자증권 Open API 포털](https://apiportal.koreainvestment.com/)
- [한국투자증권 Open API GitHub](https://github.com/koreainvestment/open-trading-api)
- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [UV Package Manager](https://docs.astral.sh/uv/)

---

## 📞 문의 및 지원

- **프로젝트**: KIS Trading API Service
- **문서 위치**: `docs/base/CLAUDE.md`
- **최종 업데이트**: 2025년 02월 (OHLCV 캐시 반영)
- **문서 버전**: 1.1

---

## ⚠️ 투자 책임 고지

**본 시스템은 한국투자증권 OPEN API를 활용한 자동매매 도구이며, 투자 조언이나 권유를 제공하지 않습니다.**

- 📈 **투자 결정 책임**: 모든 투자 결정과 그에 따른 손익은 전적으로 투자자 본인의 책임입니다
- 💰 **손실 위험**: 주식, 선물, 옵션 등 모든 금융상품 투자에는 원금 손실 위험이 있습니다
- 🔍 **정보 검증**: API를 통해 제공되는 정보의 정확성은 한국투자증권에 의존하며, 투자 전 반드시 정보를 검증하시기 바랍니다
- 🧠 **신중한 판단**: 충분한 조사와 신중한 판단 없이 투자하지 마시기 바랍니다
- 🎯 **모의투자 권장**: 실전 투자 전 반드시 모의투자를 통해 충분히 연습하시기 바랍니다

**투자는 본인의 판단과 책임 하에 이루어져야 하며, 본 시스템 사용으로 인한 어떠한 손실에 대해서도 개발자는 책임지지 않습니다.**

---

**💡 핵심 메시지**:

이 프로젝트는 **샘플 코드**에서 **엔터프라이즈급 자동매매 시스템**으로 발전하는 것을 목표로 합니다.

**헥사고날 아키텍처**와 **현대적 패턴**을 통해 유지보수성과 확장성을 확보하며, **안전하고 효율적인 자동매매 환경**을 제공합니다.
