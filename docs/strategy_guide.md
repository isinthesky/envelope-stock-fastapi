# 볼린저 밴드 + 엔벨로프 차트 매매 전략 가이드

## 목차
1. [전략 개요](#전략-개요)
2. [기술적 지표 설명](#기술적-지표-설명)
3. [매매 시그널 로직](#매매-시그널-로직)
4. [사용 방법](#사용-방법)
5. [파라미터 최적화](#파라미터-최적화)
6. [리스크 관리](#리스크-관리)

---

## 전략 개요

### 전략 유형
**평균 회귀 (Mean Reversion) 전략**

가격이 평균에서 크게 벗어났을 때, 다시 평균으로 회귀할 것으로 예상하고 매매하는 전략입니다.

### 핵심 아이디어
- **볼린저 밴드(20,2)**: 가격의 변동성을 기반으로 상/하단 밴드 형성
- **엔벨로프(20,2%)**: 이동평균선을 기준으로 일정 비율 떨어진 채널 형성
- **결합 시그널**: 두 지표가 동시에 과매도/과매수를 나타낼 때 더 신뢰도 높은 시그널

---

## 기술적 지표 설명

### 1. 볼린저 밴드 (Bollinger Bands)

```
상단 밴드 = MA(20) + 2 × σ(20)
중간 밴드 = MA(20)
하단 밴드 = MA(20) - 2 × σ(20)
```

- **MA(20)**: 20일 이동평균선
- **σ(20)**: 20일 표준편차
- **의미**: 변동성이 클수록 밴드 폭이 넓어짐

### 2. 엔벨로프 (Envelope)

```
상단 밴드 = MA(20) × (1 + 2%)
중간 밴드 = MA(20)
하단 밴드 = MA(20) × (1 - 2%)
```

- **MA(20)**: 20일 이동평균선
- **±2%**: 이동평균선에서 일정 비율만큼 떨어진 채널
- **의미**: 고정된 비율로 과매도/과매수 판단

---

## 매매 시그널 로직

### 매수 조건 (엄격 모드)
```python
if (현재가 < 볼린저 하단) AND (현재가 < 엔벨로프 하단):
    return "BUY"  # 과매도 -> 매수
```

### 매도 조건 (엄격 모드)
```python
if (현재가 > 볼린저 상단) AND (현재가 > 엔벨로프 상단):
    return "SELL"  # 과매수 -> 매도
```

### 완화 모드 (선택사항)
```python
# 하나의 지표만 만족해도 시그널 생성
if (현재가 < 볼린저 하단) OR (현재가 < 엔벨로프 하단):
    return "BUY"
```

### 시그널 강도
각 지표에서 현재가의 위치를 -2 ~ +2 범위로 수치화:
- **-2**: 하단 밴드 훨씬 아래 (강한 과매도)
- **-1**: 하단 밴드 근처
- **0**: 중간선
- **+1**: 상단 밴드 근처
- **+2**: 상단 밴드 훨씬 위 (강한 과매수)

---

## 사용 방법

### 1. 서버 실행

```bash
# 의존성 설치
uv sync

# .env 파일 설정
cp .env.example .env
# KIS_APP_KEY, KIS_APP_SECRET 등 입력

# FastAPI 서버 실행
uvicorn src.main:app --reload
```

### 2. 전략 생성 및 실행

```python
import asyncio
from examples.strategy_bollinger_envelope import (
    create_strategy,
    start_strategy,
    STRATEGY_CONFIG,
)

async def main():
    # 1. 전략 생성
    strategy = await create_strategy(STRATEGY_CONFIG)
    strategy_id = strategy["id"]

    # 2. 전략 시작
    await start_strategy(strategy_id)
    print(f"전략 실행 중: ID={strategy_id}")

asyncio.run(main())
```

### 3. 전략 모니터링

```python
from examples.strategy_bollinger_envelope import get_strategy

async def monitor():
    strategy = await get_strategy(strategy_id)

    print(f"상태: {strategy['status']}")
    print(f"총 실행: {strategy['total_executions']}회")
    print(f"성공률: {strategy['success_rate']:.1f}%")

asyncio.run(monitor())
```

### 4. 전략 중지

```python
from examples.strategy_bollinger_envelope import stop_strategy, delete_strategy

async def cleanup():
    await stop_strategy(strategy_id)
    await delete_strategy(strategy_id)

asyncio.run(cleanup())
```

---

## 파라미터 최적화

### 기본 설정 (보수적)
```json
{
  "bollinger_band": {
    "period": 20,
    "std_multiplier": 2.0
  },
  "envelope": {
    "period": 20,
    "percentage": 2.0
  }
}
```

### 공격적 설정
```json
{
  "bollinger_band": {
    "period": 10,      // 더 짧은 기간
    "std_multiplier": 1.5  // 더 좁은 밴드
  },
  "envelope": {
    "period": 10,
    "percentage": 1.5  // 더 좁은 채널
  }
}
```

### 방어적 설정
```json
{
  "bollinger_band": {
    "period": 30,      // 더 긴 기간
    "std_multiplier": 2.5  // 더 넓은 밴드
  },
  "envelope": {
    "period": 30,
    "percentage": 3.0  // 더 넓은 채널
  }
}
```

### 종목별 최적화 팁
- **변동성이 큰 종목** (예: 바이오, 테마주): 기간 짧게, 밴드 폭 넓게
- **변동성이 작은 종목** (예: 대형주): 기간 길게, 밴드 폭 좁게
- **횡보장**: 엔벨로프 비율 증가
- **추세장**: 볼린저 밴드 표준편차 배수 증가

---

## 리스크 관리

### 1. 손절/익절 설정

```json
{
  "risk_management": {
    "use_stop_loss": true,
    "stop_loss_ratio": -0.03,    // -3% 손절
    "use_take_profit": true,
    "take_profit_ratio": 0.05,    // +5% 익절
    "use_reverse_signal_exit": true  // 반대 시그널 청산
  }
}
```

### 2. 포지션 관리

```json
{
  "position": {
    "allocation_ratio": 0.1,       // 계좌의 10%씩 배분
    "max_position_count": 3        // 최대 3개 종목 동시 보유
  }
}
```

### 3. 추천 리스크 비율

| 투자 성향 | 손절 | 익절 | 자산배분 | 최대종목 |
|---------|------|------|---------|---------|
| 보수적   | -2%  | +3%  | 5%      | 2       |
| 중립적   | -3%  | +5%  | 10%     | 3       |
| 공격적   | -5%  | +8%  | 15%     | 5       |

### 4. 시장 상황별 대응

#### 변동성 확대 시
```python
# 볼린저 스퀴즈 이후 확장 구간
- 손절 비율 확대: -5%
- 포지션 크기 축소: 5%
- 체크 주기 단축: 30초
```

#### 횡보장
```python
# 방향성 없는 시장
- 익절 비율 축소: +3%
- 엔벨로프 비율 확대: 3%
- 반대 시그널 청산 활성화
```

#### 급락장
```python
# 일시적 전략 정지 권장
await pause_strategy(strategy_id)
```

---

## API 엔드포인트

### 전략 관리

```
POST   /api/v1/strategies              # 전략 생성
GET    /api/v1/strategies              # 전략 목록
GET    /api/v1/strategies/{id}         # 전략 상세
PUT    /api/v1/strategies/{id}         # 전략 수정
DELETE /api/v1/strategies/{id}         # 전략 삭제

POST   /api/v1/strategies/{id}/start   # 전략 시작
POST   /api/v1/strategies/{id}/pause   # 전략 일시정지
POST   /api/v1/strategies/{id}/stop    # 전략 중지
```

### 계좌 조회

```
GET    /api/v1/accounts/balance        # 잔고 조회
GET    /api/v1/accounts/positions      # 보유 종목 조회
```

### 주문 관리

```
POST   /api/v1/orders                  # 주문 생성
GET    /api/v1/orders                  # 주문 목록
GET    /api/v1/orders/{id}             # 주문 상세
```

---

## 문제 해결 (Troubleshooting)

### 전략이 실행되지 않음
1. 서버 로그 확인: `uvicorn src.main:app --reload`
2. 전략 상태 확인: `status` 필드가 `active`인지
3. KIS API 토큰 확인: `.env` 파일 설정
4. 충분한 차트 데이터 확인: 최소 20일 이상 필요

### 매매 시그널이 발생하지 않음
1. 현재가가 밴드 안에 있는지 확인
2. `use_strict_mode=False`로 완화 모드 시도
3. 볼린저 밴드/엔벨로프 파라미터 조정
4. 시그널 강도 로그 확인

### 손실이 계속 발생함
1. 백테스팅 먼저 수행
2. 파라미터 재최적화
3. 리스크 관리 강화 (손절 비율 축소)
4. 종목 변경 또는 전략 중지

---

## 참고 자료

- [볼린저 밴드 완벽 가이드](https://www.bollingerbands.com/)
- [기술적 분석 지표](https://www.investopedia.com/terms/b/bollingerbands.asp)
- [한국투자증권 API 문서](https://apiportal.koreainvestment.com/)

---

## 라이선스

MIT License

## 문의

이슈 등록: [GitHub Issues](https://github.com/your-repo/issues)
