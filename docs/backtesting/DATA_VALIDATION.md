# 데이터 수집 및 검증 가이드

## 📋 목차
1. [개요](#개요)
2. [데이터 수집](#데이터-수집)
3. [데이터 저장](#데이터-저장)
4. [데이터 검증](#데이터-검증)
5. [이상 데이터 처리](#이상-데이터-처리)
6. [품질 보증 체크리스트](#품질-보증-체크리스트)

---

## 개요

백테스팅의 신뢰도는 **데이터 품질**에 직접적으로 의존합니다. 부정확하거나 불완전한 데이터는 백테스팅 결과를 왜곡시켜 실전에서 예상치 못한 손실을 초래할 수 있습니다.

### 데이터 품질 목표

| 지표 | 목표 | 중요도 |
|------|------|--------|
| **결측치 비율** | 0% | 🔴 Critical |
| **이상치 탐지율** | > 99% | 🔴 Critical |
| **수정주가 정확도** | 100% | 🔴 Critical |
| **거래량 검증** | > 99.9% | 🟡 Important |
| **시간 정확도** | ±1초 | 🟢 Nice-to-have |

---

## 데이터 수집

### 1. KIS API를 통한 차트 데이터 수집

#### 일봉 데이터 수집

```python
from src.application.domain.market_data.service import MarketDataService
from datetime import datetime, timedelta

async def collect_daily_data(
    service: MarketDataService,
    symbol: str,
    start_date: datetime,
    end_date: datetime
) -> list[CandleDTO]:
    """
    일봉 데이터 수집

    Args:
        service: MarketDataService 인스턴스
        symbol: 종목코드 (예: "005930")
        start_date: 시작일
        end_date: 종료일

    Returns:
        list[CandleDTO]: 캔들 데이터 리스트
    """
    chart_data = await service.get_chart_data(
        symbol=symbol,
        interval="1d",
        start_date=start_date,
        end_date=end_date
    )

    return chart_data.candles
```

#### 수정주가 vs 원주가

KIS API는 두 가지 가격 옵션을 제공합니다:

```python
# MarketDataService 내부 (src/application/domain/market_data/service.py:218)
params = {
    "FID_ORG_ADJ_PRC": "0",  # 0: 수정주가, 1: 원주가
}
```

| 옵션 | 설명 | 백테스팅 권장 |
|------|------|--------------|
| **수정주가** | 주식 분할, 병합, 배당 등 반영한 조정가격 | ✅ **권장** |
| **원주가** | 실제 거래된 가격 (조정 전) | ❌ 비권장 |

**⚠️ 중요**: 백테스팅에는 반드시 **수정주가(0)**를 사용해야 합니다. 원주가를 사용하면 주식 분할/병합 시 가격 왜곡이 발생합니다.

#### API 제한사항

| 항목 | 제한 | 대응 방안 |
|------|------|----------|
| 요청 횟수 | 초당 20회 | Rate Limiter 구현 |
| 최대 조회 기간 | 종목별 상이 | 여러 번 나눠서 호출 |
| 타임아웃 | 30초 | Retry 로직 구현 |

```python
import asyncio
from typing import AsyncGenerator

async def collect_with_rate_limit(
    service: MarketDataService,
    symbols: list[str],
    start_date: datetime,
    end_date: datetime,
    max_requests_per_second: int = 20
) -> AsyncGenerator[tuple[str, list[CandleDTO]], None]:
    """
    Rate Limit을 고려한 데이터 수집

    Args:
        service: MarketDataService 인스턴스
        symbols: 종목 리스트
        start_date: 시작일
        end_date: 종료일
        max_requests_per_second: 초당 최대 요청 수

    Yields:
        tuple[종목코드, 캔들 데이터]
    """
    delay = 1.0 / max_requests_per_second

    for symbol in symbols:
        try:
            data = await collect_daily_data(service, symbol, start_date, end_date)
            yield (symbol, data)

            await asyncio.sleep(delay)  # Rate Limit 대응

        except Exception as e:
            print(f"⚠️ {symbol} 수집 실패: {e}")
            continue
```

### 2. 대량 데이터 수집 전략

#### 기간 분할 수집

```python
from datetime import timedelta

async def collect_long_period(
    service: MarketDataService,
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    chunk_days: int = 365  # 1년씩 분할
) -> list[CandleDTO]:
    """
    장기간 데이터를 기간별로 나눠서 수집

    Args:
        service: MarketDataService 인스턴스
        symbol: 종목코드
        start_date: 시작일
        end_date: 종료일
        chunk_days: 한 번에 조회할 기간 (일)

    Returns:
        list[CandleDTO]: 전체 기간 캔들 데이터
    """
    all_candles = []
    current_date = start_date

    while current_date < end_date:
        chunk_end = min(current_date + timedelta(days=chunk_days), end_date)

        print(f"📥 수집 중: {symbol} ({current_date.date()} ~ {chunk_end.date()})")

        candles = await collect_daily_data(
            service, symbol, current_date, chunk_end
        )
        all_candles.extend(candles)

        current_date = chunk_end
        await asyncio.sleep(0.1)  # 안정성을 위한 짧은 대기

    # 날짜순 정렬 (오래된 것부터)
    all_candles.sort(key=lambda x: x.timestamp)

    return all_candles
```

---

## 데이터 저장

### 1. PostgreSQL 저장 (권장)

#### 테이블 설계

```sql
-- 차트 데이터 테이블
CREATE TABLE chart_data (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open DECIMAL(18, 2) NOT NULL,
    high DECIMAL(18, 2) NOT NULL,
    low DECIMAL(18, 2) NOT NULL,
    close DECIMAL(18, 2) NOT NULL,
    volume BIGINT NOT NULL,
    adjusted BOOLEAN DEFAULT TRUE,  -- 수정주가 여부
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(symbol, date)  -- 중복 방지
);

CREATE INDEX idx_chart_symbol_date ON chart_data(symbol, date);
CREATE INDEX idx_chart_date ON chart_data(date);
```

#### SQLAlchemy 모델

```python
# src/adapters/database/models/chart_data.py
from sqlalchemy import Column, Integer, String, Date, Numeric, BigInteger, Boolean, DateTime, UniqueConstraint
from src.adapters.database.models.base import Base
from datetime import datetime

class ChartData(Base):
    """차트 데이터 모델"""

    __tablename__ = "chart_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Numeric(18, 2), nullable=False)
    high = Column(Numeric(18, 2), nullable=False)
    low = Column(Numeric(18, 2), nullable=False)
    close = Column(Numeric(18, 2), nullable=False)
    volume = Column(BigInteger, nullable=False)
    adjusted = Column(Boolean, default=True, comment="수정주가 여부")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint('symbol', 'date', name='uq_symbol_date'),
    )
```

#### 데이터 저장 함수

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

async def save_chart_data(
    session: AsyncSession,
    symbol: str,
    candles: list[CandleDTO]
) -> int:
    """
    차트 데이터 저장 (Upsert)

    Args:
        session: SQLAlchemy 세션
        symbol: 종목코드
        candles: 캔들 데이터 리스트

    Returns:
        int: 저장된 레코드 수
    """
    records = [
        {
            "symbol": symbol,
            "date": candle.timestamp.date(),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": candle.volume,
            "adjusted": True,
        }
        for candle in candles
    ]

    # Upsert (중복 시 업데이트)
    stmt = insert(ChartData).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=['symbol', 'date'],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "updated_at": datetime.now(),
        }
    )

    result = await session.execute(stmt)
    await session.commit()

    return result.rowcount
```

### 2. CSV 파일 저장 (백업/공유용)

```python
import pandas as pd
from pathlib import Path

def save_to_csv(
    symbol: str,
    candles: list[CandleDTO],
    output_dir: str = "./data/backtest"
) -> str:
    """
    CSV 파일로 저장

    Args:
        symbol: 종목코드
        candles: 캔들 데이터
        output_dir: 출력 디렉토리

    Returns:
        str: 저장된 파일 경로
    """
    # DataFrame 생성
    df = pd.DataFrame([
        {
            "date": candle.timestamp.date(),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": candle.volume,
        }
        for candle in candles
    ])

    # 날짜순 정렬
    df = df.sort_values("date")

    # 디렉토리 생성
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 파일 저장
    file_path = f"{output_dir}/{symbol}.csv"
    df.to_csv(file_path, index=False, encoding="utf-8-sig")

    print(f"✅ CSV 저장 완료: {file_path} ({len(df)}건)")
    return file_path
```

### 3. Redis 캐싱

```python
from src.adapters.cache.redis_client import RedisClient
import json

async def cache_chart_data(
    redis_client: RedisClient,
    symbol: str,
    candles: list[CandleDTO],
    ttl: int = 86400  # 1일
) -> None:
    """
    차트 데이터 Redis 캐싱

    Args:
        redis_client: Redis 클라이언트
        symbol: 종목코드
        candles: 캔들 데이터
        ttl: TTL (초)
    """
    cache_key = f"chart_data:{symbol}"

    data = [candle.model_dump(mode='json') for candle in candles]

    await redis_client.set(cache_key, json.dumps(data), ttl=ttl)
```

---

## 데이터 검증

### 1. 결측치 검증

#### 거래일 결측치 확인

```python
from datetime import datetime, timedelta
import pandas as pd

def validate_missing_dates(
    candles: list[CandleDTO],
    start_date: datetime,
    end_date: datetime
) -> dict[str, any]:
    """
    결측 거래일 검증

    Args:
        candles: 캔들 데이터
        start_date: 예상 시작일
        end_date: 예상 종료일

    Returns:
        dict: 검증 결과
    """
    # 실제 데이터 날짜 추출
    actual_dates = {candle.timestamp.date() for candle in candles}

    # 예상 거래일 생성 (주말 제외)
    expected_dates = set()
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # 월~금
            expected_dates.add(current.date())
        current += timedelta(days=1)

    # 결측일 확인
    missing_dates = sorted(expected_dates - actual_dates)

    return {
        "total_expected": len(expected_dates),
        "total_actual": len(actual_dates),
        "missing_count": len(missing_dates),
        "missing_dates": missing_dates[:10],  # 최대 10개만
        "coverage_rate": len(actual_dates) / len(expected_dates) if expected_dates else 0.0
    }
```

#### 결측치 보간

```python
def fill_missing_data(candles: list[CandleDTO]) -> list[CandleDTO]:
    """
    결측치 보간 (Forward Fill)

    Args:
        candles: 캔들 데이터

    Returns:
        list[CandleDTO]: 보간된 캔들 데이터
    """
    df = pd.DataFrame([
        {
            "timestamp": c.timestamp,
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": c.volume,
        }
        for c in candles
    ])

    # 날짜 인덱스 설정
    df = df.set_index("timestamp")
    df = df.sort_index()

    # 결측치 Forward Fill (이전 값으로 채우기)
    df = df.asfreq('D', method='ffill')

    # CandleDTO로 변환
    filled_candles = [
        CandleDTO(
            timestamp=idx.to_pydatetime(),
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=int(row["volume"]),
        )
        for idx, row in df.iterrows()
    ]

    return filled_candles
```

### 2. 이상치 검증

#### 가격 이상치 탐지

```python
def detect_price_outliers(candles: list[CandleDTO], z_threshold: float = 5.0) -> list[dict]:
    """
    가격 이상치 탐지 (Z-Score 방식)

    Args:
        candles: 캔들 데이터
        z_threshold: Z-Score 임계값 (기본 5.0)

    Returns:
        list[dict]: 이상치 리스트
    """
    df = pd.DataFrame([
        {
            "date": c.timestamp.date(),
            "close": float(c.close),
            "daily_return": None,
        }
        for c in candles
    ])

    # 일일 수익률 계산
    df["daily_return"] = df["close"].pct_change()

    # Z-Score 계산
    mean_return = df["daily_return"].mean()
    std_return = df["daily_return"].std()
    df["z_score"] = (df["daily_return"] - mean_return) / std_return

    # 이상치 필터링
    outliers = df[abs(df["z_score"]) > z_threshold]

    return outliers.to_dict('records')
```

#### OHLC 관계 검증

```python
def validate_ohlc_relationship(candles: list[CandleDTO]) -> list[dict]:
    """
    OHLC 관계 검증 (High >= Open, Close >= Low)

    Args:
        candles: 캔들 데이터

    Returns:
        list[dict]: 위반 사례
    """
    violations = []

    for candle in candles:
        issues = []

        # High가 가장 높은지
        if candle.high < candle.open or candle.high < candle.close:
            issues.append("High < Open or Close")

        # Low가 가장 낮은지
        if candle.low > candle.open or candle.low > candle.close:
            issues.append("Low > Open or Close")

        # High >= Low
        if candle.high < candle.low:
            issues.append("High < Low")

        if issues:
            violations.append({
                "date": candle.timestamp.date(),
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "issues": issues,
            })

    return violations
```

### 3. 거래량 검증

```python
def validate_volume(candles: list[CandleDTO]) -> dict[str, any]:
    """
    거래량 검증

    Args:
        candles: 캔들 데이터

    Returns:
        dict: 검증 결과
    """
    volumes = [c.volume for c in candles]

    zero_volume_count = sum(1 for v in volumes if v == 0)
    negative_volume_count = sum(1 for v in volumes if v < 0)

    return {
        "total_count": len(volumes),
        "zero_volume_count": zero_volume_count,
        "negative_volume_count": negative_volume_count,
        "zero_volume_ratio": zero_volume_count / len(volumes) if volumes else 0.0,
        "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
        "max_volume": max(volumes) if volumes else 0,
        "min_volume": min(volumes) if volumes else 0,
    }
```

---

## 이상 데이터 처리

### 1. 휴장일 처리

#### KRX 휴장일 API 활용

```python
async def check_holiday(service: MarketDataService, date: datetime) -> bool:
    """
    휴장일 여부 확인

    Args:
        service: MarketDataService
        date: 확인할 날짜

    Returns:
        bool: 휴장일이면 True
    """
    # KIS API의 휴장일 조회 TR 활용
    # TR_ID: CTCA0903R (국내휴장일조회)
    # 실제 구현은 KIS API 문서 참조

    # 주말은 항상 휴장
    if date.weekday() >= 5:
        return True

    # 공휴일 확인 (API 호출)
    # ... API 호출 로직

    return False
```

#### 휴장일 제외 전처리

```python
async def filter_holidays(
    candles: list[CandleDTO],
    service: MarketDataService
) -> list[CandleDTO]:
    """
    휴장일 데이터 제거

    Args:
        candles: 캔들 데이터
        service: MarketDataService

    Returns:
        list[CandleDTO]: 휴장일 제거된 캔들 데이터
    """
    filtered = []

    for candle in candles:
        is_holiday = await check_holiday(service, candle.timestamp)

        if not is_holiday:
            filtered.append(candle)

    return filtered
```

### 2. 주식 분할/병합 조정

**⚠️ 중요**: KIS API에서 수정주가(`FID_ORG_ADJ_PRC="0"`)를 사용하면 자동으로 조정됩니다.

#### 수동 조정이 필요한 경우

```python
def adjust_for_split(
    candles: list[CandleDTO],
    split_date: datetime,
    split_ratio: float  # 예: 1:5 분할이면 5.0
) -> list[CandleDTO]:
    """
    주식 분할 수동 조정

    Args:
        candles: 캔들 데이터
        split_date: 분할 기준일
        split_ratio: 분할 비율

    Returns:
        list[CandleDTO]: 조정된 캔들 데이터
    """
    adjusted = []

    for candle in candles:
        if candle.timestamp < split_date:
            # 분할 이전 데이터는 가격을 나누고 거래량을 곱함
            adjusted.append(
                CandleDTO(
                    timestamp=candle.timestamp,
                    open=candle.open / Decimal(str(split_ratio)),
                    high=candle.high / Decimal(str(split_ratio)),
                    low=candle.low / Decimal(str(split_ratio)),
                    close=candle.close / Decimal(str(split_ratio)),
                    volume=int(candle.volume * split_ratio),
                )
            )
        else:
            # 분할 이후는 그대로
            adjusted.append(candle)

    return adjusted
```

### 3. 이상치 처리 전략

| 이상치 유형 | 처리 방법 | 구현 |
|-----------|----------|------|
| **OHLC 관계 위반** | 데이터 제거 또는 보정 | 해당 날짜 제거 |
| **거래량 0** | 전일 데이터로 대체 | Forward Fill |
| **급격한 가격 변동** | 뉴스 확인 후 판단 | 수동 검토 |
| **결측일** | 전일 종가로 채우기 | Forward Fill |

```python
def clean_outliers(candles: list[CandleDTO]) -> list[CandleDTO]:
    """
    이상치 정제

    Args:
        candles: 원본 캔들 데이터

    Returns:
        list[CandleDTO]: 정제된 캔들 데이터
    """
    # 1. OHLC 관계 검증
    violations = validate_ohlc_relationship(candles)
    violation_dates = {v["date"] for v in violations}

    # 2. 위반 데이터 제거
    cleaned = [c for c in candles if c.timestamp.date() not in violation_dates]

    # 3. 거래량 0인 경우 전일 데이터로 대체
    cleaned = fill_missing_data(cleaned)

    print(f"✅ 정제 완료: 원본 {len(candles)}건 → 정제 {len(cleaned)}건 (제거 {len(violation_dates)}건)")

    return cleaned
```

---

## 품질 보증 체크리스트

### 수집 전 체크리스트

- [ ] KIS API 토큰 유효성 확인
- [ ] 수집 기간 설정 (최소 1년, 권장 3-5년)
- [ ] 종목 리스트 검증 (상장폐지 종목 제외)
- [ ] Rate Limit 설정 (초당 20회)
- [ ] 저장 공간 확인 (종목당 약 1MB)

### 수집 후 체크리스트

- [ ] **결측치 0% 달성**
  ```python
  result = validate_missing_dates(candles, start_date, end_date)
  assert result["missing_count"] == 0, f"결측일 {result['missing_count']}건 발견"
  ```

- [ ] **OHLC 관계 검증 통과**
  ```python
  violations = validate_ohlc_relationship(candles)
  assert len(violations) == 0, f"OHLC 위반 {len(violations)}건"
  ```

- [ ] **거래량 검증 통과**
  ```python
  vol_result = validate_volume(candles)
  assert vol_result["negative_volume_count"] == 0, "음수 거래량 발견"
  ```

- [ ] **가격 이상치 확인**
  ```python
  outliers = detect_price_outliers(candles)
  if outliers:
      print(f"⚠️ 이상치 {len(outliers)}건 확인 필요")
  ```

- [ ] **데이터베이스 저장 확인**
  ```python
  saved_count = await save_chart_data(session, symbol, candles)
  assert saved_count == len(candles), "저장 실패"
  ```

### 백테스팅 전 체크리스트

- [ ] 수정주가 사용 확인
- [ ] 생존 편향 고려 (상장폐지 종목 포함 여부)
- [ ] 충분한 데이터 기간 (최소 20일 이상)
- [ ] 휴장일 제거 완료
- [ ] 데이터 정렬 (날짜 오름차순)

---

## 자동화 스크립트

### 전체 파이프라인

```python
async def data_collection_pipeline(
    symbols: list[str],
    start_date: datetime,
    end_date: datetime,
    service: MarketDataService,
    session: AsyncSession
) -> dict[str, any]:
    """
    데이터 수집 전체 파이프라인

    Args:
        symbols: 종목 리스트
        start_date: 시작일
        end_date: 종료일
        service: MarketDataService
        session: SQLAlchemy 세션

    Returns:
        dict: 수집 결과 요약
    """
    results = {
        "success": [],
        "failed": [],
        "total_records": 0,
    }

    for symbol in symbols:
        try:
            print(f"\n📊 처리 중: {symbol}")

            # 1. 데이터 수집
            candles = await collect_long_period(symbol, start_date, end_date)
            print(f"  ✅ 수집: {len(candles)}건")

            # 2. 데이터 검증
            missing_result = validate_missing_dates(candles, start_date, end_date)
            print(f"  ✅ 커버리지: {missing_result['coverage_rate']*100:.1f}%")

            ohlc_violations = validate_ohlc_relationship(candles)
            if ohlc_violations:
                print(f"  ⚠️ OHLC 위반: {len(ohlc_violations)}건")

            # 3. 이상치 정제
            cleaned = clean_outliers(candles)

            # 4. 데이터베이스 저장
            saved_count = await save_chart_data(session, symbol, cleaned)
            print(f"  ✅ 저장: {saved_count}건")

            # 5. CSV 백업
            save_to_csv(symbol, cleaned)

            results["success"].append(symbol)
            results["total_records"] += saved_count

        except Exception as e:
            print(f"  ❌ 실패: {e}")
            results["failed"].append({"symbol": symbol, "error": str(e)})

    print(f"\n{'='*60}")
    print(f"🎉 수집 완료: 성공 {len(results['success'])}개, 실패 {len(results['failed'])}개")
    print(f"📊 총 레코드: {results['total_records']:,}건")

    return results
```

### 사용 예제

```python
from datetime import datetime
import asyncio

async def main():
    """메인 실행"""
    # 초기화
    service = MarketDataService(kis_client, redis_client)

    # 종목 리스트
    symbols = [
        "005930",  # 삼성전자
        "000660",  # SK하이닉스
        "035420",  # NAVER
    ]

    # 기간 설정
    start_date = datetime(2020, 1, 1)
    end_date = datetime(2024, 12, 31)

    # 파이프라인 실행
    results = await data_collection_pipeline(
        symbols, start_date, end_date, service, session
    )

    # 결과 출력
    if results["failed"]:
        print(f"\n⚠️ 실패한 종목:")
        for item in results["failed"]:
            print(f"  - {item['symbol']}: {item['error']}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 문의 및 지원

데이터 수집/검증 관련 문의는 GitHub Issues로 등록해주세요.

- GitHub: [프로젝트 이슈](https://github.com/isinthesky/envelope-stock-fastapi/issues)

---

**마지막 업데이트**: 2025-10-22
**문서 버전**: 1.0
