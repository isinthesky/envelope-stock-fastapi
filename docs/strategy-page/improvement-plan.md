# 매수/매도 전략 페이지 개선 계획

> ⚠️ **[2026-08-02 갱신] MA5 돌파 전략 제거됨.** 본문의 `buyStrategy.ma5Scan` localStorage 키,
> `ma5` 쿨다운(3분), "MA5 돌파 스캔" 라벨 등 MA5 관련 서술은 무효입니다. 현재 매수는 골든크로스 단일.

작성일: 2026-01-26

## 요청 사항
- 마지막 전략 계산식 결과가 화면에 항상 출력되도록 개선
- 주식 종목 리스트 위에 마지막 호출 날짜와 시간을 표시
- 반복적인 버튼 클릭을 방지

## 현재 상태 분석

### 매수 전략 페이지 (`templates/page/strategy.html`)

**기존 기능:**
- localStorage 키: `buyStrategy.gcScan`, `buyStrategy.ma5Scan`
- `loadSavedScans()` 함수: 페이지 로드 시 localStorage에서 스캔 결과 복원
- `updateLastSearchLabel()` 함수: 마지막 검색 시간 표시
- `saveLastScan()` 함수: 스캔 결과를 localStorage에 저장

**현재 동작:**
```javascript
document.addEventListener('DOMContentLoaded', () => {
  loadBuyHistory();   // DB에서 히스토리 로드
  loadSavedScans();   // localStorage에서 스캔 결과 복원
});
```

**문제점:**
1. 마지막 검색 라벨이 작은 글씨로 표시되어 눈에 띄지 않음 (12px, 회색)
2. 스캔 결과 컨테이너가 `display:none`으로 시작하여 복원 전까지 빈 화면
3. 버튼 상태가 최근 검색 여부를 반영하지 않음

### 매도 전략 페이지 (`templates/page/sell_strategy.html`)

**기존 기능:**
- localStorage 키: `sellStrategy.lastAnalysis`
- `loadLastAnalysis()` 함수: localStorage에서 마지막 분석 결과 로드
- `updateLastAnalysisLabel()` 함수: 마지막 분석 시간 표시
- `saveLastAnalysis()` 함수: 분석 결과를 localStorage에 저장

**현재 동작:**
```javascript
document.addEventListener('DOMContentLoaded', () => {
  const saved = loadLastAnalysis();
  if (saved) {
    displayResult({...saved, sell_reasons: normalizeSellReasons(saved)});
    updateLastAnalysisLabel(saved);
  }
  loadHistory();  // DB 히스토리와 비교하여 최신 결과 표시
});
```

**문제점:**
1. 마지막 분석 라벨이 작은 글씨로 표시되어 눈에 띄지 않음
2. 분석 버튼에 최근 분석 상태가 표시되지 않음

---

## 개선 계획

### Phase 1: 마지막 검색/분석 정보 강화

#### 1.1 매수 전략 페이지
- [ ] 마지막 검색 라벨 스타일 강화 (더 큰 폰트, 배경색)
- [ ] 검색 결과 유효 시간 표시 (예: "2시간 전 검색")
- [ ] 스캔 버튼에 마지막 검색 시간 표시 (툴팁 또는 부제)

#### 1.2 매도 전략 페이지
- [ ] 마지막 분석 라벨 스타일 강화
- [ ] 분석 결과 유효 시간 표시
- [ ] 분석 버튼에 마지막 분석 시간 표시

### Phase 2: 결과 항상 표시

#### 2.1 매수 전략 페이지
- [ ] 페이지 로드 시 저장된 스캔 결과가 있으면 즉시 표시
- [ ] 결과 컨테이너 초기 상태를 "마지막 결과 로딩 중..."으로 변경
- [ ] 저장된 결과가 없으면 "아직 검색 결과가 없습니다" 메시지 표시

#### 2.2 매도 전략 페이지
- [ ] 페이지 로드 시 저장된 분석 결과가 있으면 즉시 표시
- [ ] 결과 섹션 초기 상태를 안내 메시지로 변경

### Phase 3: 중복 클릭 방지

#### 3.1 공통
- [ ] 검색/분석 후 일정 시간(예: 5분) 내 재클릭 시 확인 대화상자 표시
- [ ] 버튼에 마지막 실행 시간 표시로 시각적 피드백 제공
- [ ] 캐시된 결과가 최신(예: 1시간 이내)이면 자동 복원 + 알림

---

## 상세 구현 사항

### 1. 마지막 검색 라벨 스타일 개선

**Before (현재):**
```css
.last-search { font-size: 12px; color: #64748b; margin-top: 6px; }
```

**After (개선):**
```css
.last-search {
  font-size: 13px;
  color: #1e40af;
  margin-top: 8px;
  padding: 8px 12px;
  background: #eff6ff;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
}
.last-search.stale {
  background: #fef3c7;
  border-left-color: #f59e0b;
  color: #92400e;
}
```

### 2. 상대 시간 표시 함수 추가

```javascript
const getRelativeTime = (dateStr) => {
  if (!dateStr) return null;
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (mins < 1) return '방금 전';
  if (mins < 60) return `${mins}분 전`;
  if (hours < 24) return `${hours}시간 전`;
  return `${days}일 전`;
};
```

### 3. 버튼 중복 클릭 방지

```javascript
const confirmRescan = (lastTime, thresholdMinutes = 5) => {
  if (!lastTime) return true;
  const elapsed = (Date.now() - new Date(lastTime).getTime()) / 60000;
  if (elapsed < thresholdMinutes) {
    const relTime = getRelativeTime(lastTime);
    return confirm(`${relTime}에 이미 검색했습니다. 다시 검색하시겠습니까?`);
  }
  return true;
};
```

### 4. 결과 컨테이너 초기 상태 개선

**매수 전략:**
```html
<div id="gc_scan_container" style="margin-top: 16px;">
  <div id="gc_loading_placeholder" class="placeholder-message">
    저장된 스캔 결과를 불러오는 중...
  </div>
  <!-- 기존 테이블 구조 -->
</div>
```

**매도 전략:**
```html
<section id="result_section">
  <h2>분석 결과</h2>
  <div id="result_container">
    <div class="placeholder-message">
      종목 코드를 입력하고 분석 버튼을 클릭하세요.
    </div>
  </div>
</section>
```

---

## 파일 변경 목록

1. `templates/page/strategy.html`
   - CSS: `.last-search` 스타일 강화
   - JS: `getRelativeTime()` 함수 추가
   - JS: `confirmRescan()` 함수 추가
   - JS: `updateLastSearchLabel()` 함수 개선
   - HTML: 결과 컨테이너 초기 상태 변경

2. `templates/page/sell_strategy.html`
   - CSS: `.last-search` 스타일 강화
   - JS: `getRelativeTime()` 함수 추가
   - JS: `confirmRescan()` 함수 추가
   - JS: `updateLastAnalysisLabel()` 함수 개선
   - HTML: 결과 섹션 초기 상태 변경

---

## 테스트 계획

1. **페이지 로드 테스트**
   - localStorage에 저장된 데이터가 있을 때 즉시 표시되는지 확인
   - 마지막 검색 시간이 올바르게 표시되는지 확인

2. **중복 클릭 방지 테스트**
   - 5분 이내 재클릭 시 확인 대화상자 표시되는지 확인
   - 확인 취소 시 스캔이 실행되지 않는지 확인

3. **스타일 테스트**
   - 마지막 검색 라벨이 눈에 잘 띄는지 확인
   - 오래된 데이터(1시간+)일 경우 경고 스타일 적용되는지 확인

---

## Codex 리뷰 결과 및 보완 사항

### 리뷰 일시: 2026-01-26

### 1. [High] 날짜 파싱 안정성 개선

**문제점:**
- `new Date(dateStr)`가 ISO 형식이 아닌 문자열에서 `Invalid Date` 반환 가능
- 미래 타임스탬프가 "방금 전"으로 표시되는 버그

**해결책:**
```javascript
const getRelativeTime = (dateStr) => {
  if (!dateStr) return null;
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return null;  // Invalid Date 처리

  const diff = Date.now() - date.getTime();
  if (diff < 0) return '잠시 후';  // 미래 타임스탬프 처리

  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (mins < 1) return '방금 전';
  if (mins < 60) return `${mins}분 전`;
  if (hours < 24) return `${hours}시간 전`;
  return `${days}일 전`;
};
```

### 2. [Medium] confirmRescan NaN 방지

**문제점:**
- 유효하지 않은 날짜에서 "NaN일 전" 표시 가능

**해결책:**
```javascript
const confirmRescan = (lastTime, thresholdMinutes = 5) => {
  if (!lastTime) return true;
  const date = new Date(lastTime);
  if (isNaN(date.getTime())) return true;  // 유효하지 않으면 허용

  const elapsed = (Date.now() - date.getTime()) / 60000;
  if (elapsed < thresholdMinutes) {
    const relTime = getRelativeTime(lastTime) || '최근';
    return confirm(`${relTime}에 이미 검색했습니다. 다시 검색하시겠습니까?`);
  }
  return true;
};
```

### 3. [Medium] localStorage 캐시 전략 개선

**문제점:**
- TTL/스키마 버전 관리 부재
- DB 히스토리와의 우선순위 불명확

**해결책:**
```javascript
const CACHE_SCHEMA_VERSION = 1;
const CACHE_TTL_MS = 3600000;  // 1시간

const saveLastScan = (key, data, timestamp) => {
  try {
    localStorage.setItem(key, JSON.stringify({
      schemaVersion: CACHE_SCHEMA_VERSION,
      savedAt: Date.now(),
      timestamp,
      data
    }));
  } catch (e) {
    console.warn('Failed to save cache:', e);
  }
};

const loadLastScan = (key) => {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;

    const cached = JSON.parse(raw);

    // 스키마 버전 검증
    if (cached.schemaVersion !== CACHE_SCHEMA_VERSION) {
      localStorage.removeItem(key);
      return null;
    }

    // TTL 검증
    const age = Date.now() - (cached.savedAt || 0);
    const isStale = age > CACHE_TTL_MS;

    return { ...cached, isStale };
  } catch (e) {
    console.warn('Failed to load cache:', e);
    return null;
  }
};
```

### 4. [Medium] 중복 클릭 방지 전략 개선

**문제점:**
- 고정 5분 임계값이 모든 스캔 유형에 적합하지 않음
- `confirm()` 모달이 현대적 UX와 맞지 않음

**해결책:**
- 스캔 유형별 임계값 설정
- In-flight 잠금 + "강제 새로고침" 버튼 제공

```javascript
const SCAN_THRESHOLDS = {
  gc: { cooldownMs: 300000, label: '골든크로스 스캔' },     // 5분
  ma5: { cooldownMs: 180000, label: 'MA5 돌파 스캔' },     // 3분
  sell: { cooldownMs: 60000, label: '매도 분석' }          // 1분
};

let scanInProgress = {};

const canScan = (scanType) => {
  if (scanInProgress[scanType]) {
    return { allowed: false, reason: '스캔 진행 중...' };
  }

  const threshold = SCAN_THRESHOLDS[scanType];
  const cached = loadLastScan(scanType);
  if (!cached) return { allowed: true };

  const elapsed = Date.now() - (cached.savedAt || 0);
  if (elapsed < threshold.cooldownMs) {
    const remaining = Math.ceil((threshold.cooldownMs - elapsed) / 60000);
    return {
      allowed: false,
      reason: `${remaining}분 후 재검색 가능`,
      forceAllowed: true  // 강제 실행 허용
    };
  }
  return { allowed: true };
};
```

### 5. [Low] Placeholder 상태 관리 개선

**문제점:**
- localStorage 비어있거나 파싱 실패 시 로딩 상태 지속 가능

**해결책:**
```javascript
const initializeResultContainer = (containerId, placeholderId) => {
  const container = document.getElementById(containerId);
  const placeholder = document.getElementById(placeholderId);

  const cached = loadLastScan(containerId);
  if (cached?.data) {
    displayResults(cached.data, cached.isStale);
    if (placeholder) placeholder.style.display = 'none';
  } else {
    if (placeholder) {
      placeholder.textContent = '저장된 검색 결과가 없습니다. 스캔 버튼을 클릭하세요.';
      placeholder.classList.add('empty-state');
    }
  }
};
```

### 6. 추가 UX 개선 제안 (Codex)

1. **캐시 상태 표시**: "cached" vs "fresh" 인디케이터 추가
2. **절대 시간 툴팁**: 상대 시간에 마우스 오버 시 절대 시간 표시
3. **버튼 비활성화**: 요청 진행 중 버튼 비활성화
4. **공유 유틸리티**: 중복 헬퍼 함수를 공용 JS 모듈로 분리
5. **접근성**: ARIA live region으로 상태 변경 알림

---

## 최종 구현 우선순위

1. **P0**: ✅ 날짜 파싱 안정성 개선 (Invalid Date, 미래 타임스탬프 처리)
2. **P0**: ✅ Placeholder 상태 관리 (빈 상태/오류 처리)
3. **P1**: ✅ localStorage 캐시 전략 개선 (스키마 버전, TTL)
4. **P1**: ✅ 마지막 검색 라벨 스타일 강화
5. **P2**: ✅ 중복 클릭 방지 (스캔 유형별 임계값)
6. **P3**: ✅ 캐시 상태 인디케이터 (캐시됨/최신)

---

## 구현 완료 (2026-01-26)

### 변경 파일
- `templates/page/strategy.html`
- `templates/page/sell_strategy.html`

### 주요 변경사항

1. **마지막 검색 라벨 스타일 강화**
   - 배경색, 테두리, 시간 뱃지 추가
   - stale 상태일 때 경고 색상 표시

2. **상대 시간 표시 (getRelativeTime)**
   - Invalid Date 안전 처리
   - 미래 타임스탬프 "잠시 후" 표시

3. **캐시 전략 개선**
   - 스키마 버전 관리 (CACHE_SCHEMA_VERSION)
   - TTL 검증 (1시간)
   - 구버전 형식 호환성 유지

4. **중복 클릭 방지**
   - 스캔 유형별 쿨다운 (GC: 5분, MA5: 3분, 매도: 1분)
   - In-flight 잠금 (scanInProgress)
   - 강제 새로고침 옵션

5. **Placeholder 메시지**
   - 저장된 결과 없음 안내
   - 필터 결과 없음 안내
   - 로딩 중 상태 표시

6. **캐시 표시 분리 (persist 옵션)**
   - 캐시 로드 시 savedAt 갱신 방지
   - 캐시됨/최신 인디케이터 표시

7. **활성 종목 갱신 결과 저장** (2026-01-27 추가)
   - 매수/매도 전략 페이지 모두 적용
   - 마지막 갱신 시간 및 갱신된 종목 수 localStorage 저장
   - 페이지 재방문 시 자동 복원
   - 1분 쿨다운으로 중복 갱신 방지
   - 버튼 비활성화 및 "갱신 중..." 상태 표시
   - API 실패 시 사용자 피드백 (에러 메시지 표시)
   - localStorage 용량 최적화 (메타데이터만 저장, items 배열 제외)
   - 스키마 불일치 시 잘못된 캐시 데이터 자동 제거
