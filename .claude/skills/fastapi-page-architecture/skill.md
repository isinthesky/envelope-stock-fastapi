---
name: fastapi-page-architecture
description: FastAPI + Jinja2 기반 페이지 아키텍처. Page Router(GET only), Template 상속, CSS/JS 모듈 분리, API 기반 데이터 흐름을 따르는 엄격한 규칙과 구조를 정의합니다.
---

# FastAPI Page Architecture

## 개요

FastAPI + Jinja2 기반 관리자/클라이언트 페이지 아키텍처입니다.
서버 로직은 API 호출로만 수행하며, UI는 Template + JS 모듈 구조로 분리합니다.

> **관련 스킬**:
> - API 서버 전체 구조: `fastapi-api-server-structure` (이 스킬은 Interface Layer 중 Pages 부분을 상세히 다룹니다)
> - 레이어 의존성 분석: `layer-optimize`

## 핵심 원칙

1. **Page Router는 GET only** - Template 반환만 담당, CUD 작업은 API Router 재활용
2. **Template은 정적 레이아웃** - 동적 렌더링은 JS가 담당
3. **역할별 분리** - Admin/Client 등 역할별 라우터와 템플릿 분리
4. **CSS Layer 기반** - `@layer`를 활용한 레이어 구조, 테마 분리
5. **JS 모듈화** - 페이지별/기능별 JS 분리

### 인증 규칙 (쿠키 기반 SSR + API)

--- 쿠키 기반 SSR+API로 인증 흐름 통일

- 페이지/API 호출에서 Bearer 토큰 주입·스토리지 저장 로직 제거
- 로그아웃 엔드포인트를 token/logout으로 정합화하고 APP_COOKIE_NAME 쿠키 삭제 보강 ---

추가 규칙:
- **페이지 렌더링(SSR)**: `current_user`, `auth_role`, `nav_items` 등은 서버에서 주입하고 템플릿은 그대로 렌더링합니다.
- **API 호출(JS)**: `Authorization: Bearer ...` 헤더를 직접 주입하지 않습니다. same-origin 쿠키를 기본으로 사용합니다.
- **토큰 저장 금지**: `localStorage/sessionStorage`에 access token/refresh token을 저장하지 않습니다.
- **로그아웃**: UI 로그아웃은 `POST /api/v1/auth/token/logout`를 호출하여 서버에서 쿠키/토큰을 정리합니다.

---

## 디렉토리 구조

### Page Router 구조
```
src/application/interface/pages/
├── client_page.py               # 클라이언트/공개 페이지
│                                 # GET /{resource_type}/{resource_id}
│                                 # GET /{resource_type}/viewer/{number}
│                                 # GET /{resource_type}/list
└── admin/
    ├── __init__.py              # admin_router 통합
    ├── common.py                # 공통 유틸 (templates, nav_links, to_kst)
    ├── dashboard.py             # GET /page/{app}/ → dashboard.html
    ├── logs.py                  # GET /page/{app}/logs
    ├── statistics.py            # GET /page/{app}/statistics
    ├── resources.py             # GET /page/{app}/resources
    └── settings.py              # GET /page/{app}/settings
```

### Static Assets 구조
```
static/{app}/
├── css/
│   ├── layers.css              # CSS Layer 정의 (@layer base, layout, ...)
│   ├── base.css                # 기본 스타일, CSS 변수
│   ├── layout.css              # 레이아웃
│   ├── components.css          # 공통 컴포넌트
│   ├── utilities.css           # 유틸리티 클래스
│   ├── animations.css          # 애니메이션
│   ├── themes/                 # 리소스 타입별 테마
│   │   ├── default.css
│   │   ├── {theme-a}.css
│   │   └── {theme-b}.css
│   └── admin/                  # 관리자 전용 CSS
│       ├── dashboard.css
│       └── icons.css
├── js/
│   ├── main.js                 # 클라이언트 페이지 메인 JS
│   ├── format.js               # 날짜/시간 포맷 유틸
│   ├── utils.js                # 공통 유틸리티
│   ├── viewer.js               # 뷰어 페이지
│   └── list.js                 # 목록 페이지
└── admin/
    ├── admin.css               # 관리자 공통 CSS
    ├── admin.js                # 관리자 공통 JS
    └── vendor/                 # 외부 라이브러리
        ├── bootstrap/
        └── chartjs/
```

### Templates 구조
```
templates/
├── base.html                   # 클라이언트 페이지 베이스 (CSS layer 포함)
├── client/                     # 클라이언트/리소스별 템플릿
│   ├── detail.html
│   ├── viewer.html
│   ├── list.html
│   └── themes/                 # 테마별 오버라이드 (선택)
│       ├── {theme-a}.html
│       └── {theme-b}.html
└── admin/
    ├── layout.html             # 관리자 베이스 (Bootstrap)
    ├── dashboard.html
    ├── logs.html
    ├── log_detail.html
    ├── statistics.html
    ├── resources.html
    ├── resource_detail.html
    └── settings.html
```

---

## Page Router 규칙

### Admin 라우터 기본 구조
```python
# src/application/interface/pages/admin/{feature}.py

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from .common import (
    get_analytics_service,
    get_monitoring_service,
    get_nav_links,
    logger,
    templates,
    to_kst,
)

router = APIRouter()


@router.get("/page/{app}/{feature}", response_class=HTMLResponse)
async def feature_page(
    request: Request,
    param: Optional[str] = Query(None, description="파라미터"),
):
    """기능 페이지."""
    try:
        # 도메인 서비스 호출
        data = get_some_service().get_data()

        context = {
            "request": request,
            "app_title": "{App Name} 관리",
            "page_title": "기능명",
            "nav_links": get_nav_links("/page/{app}/{feature}"),
            "current_path": "/page/{app}/{feature}",
            "generated_at": datetime.utcnow(),
            "to_kst": to_kst,
            "data": data,
        }

        return templates.TemplateResponse("admin/{feature}.html", context)

    except Exception as exc:
        logger.error("Error in feature page: %s", exc)
        raise HTTPException(500, "Internal server error") from exc
```

### Admin 라우터 통합
```python
# src/application/interface/pages/admin/__init__.py

from __future__ import annotations

from fastapi import APIRouter

from . import dashboard, logs, resources, settings, statistics

router = APIRouter(tags=["admin-pages"])

router.include_router(dashboard.router)
router.include_router(logs.router)
router.include_router(statistics.router)
router.include_router(resources.router)
router.include_router(settings.router)

__all__ = ["router"]
```

### Admin 공통 유틸리티
```python
# src/application/interface/pages/admin/common.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import List

from fastapi.templating import Jinja2Templates

from src.application.domain.services.analytics import AnalyticsService
from src.application.domain.services.monitoring import MonitoringService
from src.application.interface.api.dependencies import get_settings, get_storage

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")


def to_kst(dt: datetime | None) -> datetime | None:
    """Convert naive/UTC datetime to KST (+09:00)."""
    if dt is None:
        return None
    kst = timezone(timedelta(hours=9))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(kst)
    return dt.astimezone(kst)


def get_analytics_service() -> AnalyticsService:
    """Analytics 도메인 서비스 의존성 주입."""
    settings = get_settings()
    return AnalyticsService(settings.DATABASE_URL)


def get_nav_links(current_path: str) -> List[dict]:
    """관리자 페이지 네비게이션 링크."""
    links = [
        {"name": "대시보드", "url": "/page/{app}/"},
        {"name": "로그", "url": "/page/{app}/logs"},
        {"name": "통계", "url": "/page/{app}/statistics"},
        {"name": "리소스", "url": "/page/{app}/resources"},
        {"name": "설정", "url": "/page/{app}/settings"},
    ]
    for link in links:
        link["active"] = current_path == link["url"] or current_path.startswith(link["url"] + "/")
    return links


__all__ = ["logger", "templates", "to_kst", "get_analytics_service", "get_nav_links"]
```

### Client 페이지 라우터 구조
```python
# src/application/interface/pages/client_page.py

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")

# 리소스 타입별 설정
RESOURCE_CONFIGS = {
    "type-a": {"name": "Type A", "logo": "/static/{app}/logo-a.png", "theme_color": "#3498db"},
    "type-b": {"name": "Type B", "logo": "/static/{app}/logo-b.png", "theme_color": "#e74c3c"},
    # ...
}


@router.get("/{resource_type}/{resource_id}", response_class=HTMLResponse)
async def resource_detail_page(
    request: Request,
    resource_type: Literal["type-a", "type-b", ...] = Path(...),
    resource_id: str = Path(...),
    mode: Optional[str] = None,
):
    """리소스 상세 페이지"""
    # 메타데이터 조회 및 TTL 확인
    # 템플릿 렌더링
    return templates.TemplateResponse(
        f"client/detail.html",  # 또는 테마별: f"client/themes/{resource_type}.html"
        {
            "request": request,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_config": RESOURCE_CONFIGS.get(resource_type),
            "items": [...],
            # ...
        },
    )


@router.get("/{resource_type}/viewer/{number}", response_class=HTMLResponse)
async def viewer_page(request: Request, resource_type: str, number: int):
    """리소스 타입별 뷰어 페이지 (컨텐츠 자동 재생)"""
    # ...


@router.get("/{resource_type}/list", response_class=HTMLResponse)
async def list_page(request: Request, resource_type: str):
    """리소스 타입별 목록 페이지"""
    # ...
```

### main.py 라우터 등록
```python
# src/main.py

from src.application.interface.pages.client_page import router as client_router
from src.application.interface.pages.admin import router as admin_router

# Static files
app.mount("/static/{app}", StaticFiles(directory="static/{app}"), name="static")

# Page routers (admin pages first to avoid conflicts with generic patterns)
app.include_router(admin_router)   # Admin: /page/{app}/*
app.include_router(client_router)  # Client: /{resource_type}/*
```

---

## Template 상속 구조

### 1단계: 클라이언트 base.html (CSS Layer 기반)
```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ resource_config.name }}{% endblock %}</title>

    <!-- CSS with Cascade Layers -->
    <link rel="stylesheet" href="/static/{app}/css/layers.css?v={version}">
    <link rel="stylesheet" href="/static/{app}/css/base.css?v={version}">
    <link rel="stylesheet" href="/static/{app}/css/layout.css?v={version}">
    <link rel="stylesheet" href="/static/{app}/css/components.css?v={version}">
    <link rel="stylesheet" href="/static/{app}/css/utilities.css?v={version}">
    <link rel="stylesheet" href="/static/{app}/css/animations.css?v={version}">
    <!-- Dynamic Theme Layer -->
    <link rel="stylesheet" href="/static/{app}/css/themes/{{ resource_type }}.css?v={version}"
        onerror="this.onerror=null;this.href='/static/{app}/css/themes/default.css';">
    {% block extra_css %}{% endblock %}
</head>
<body class="{{ resource_type }}-theme" style="--theme-color: {{ resource_config.theme_color }};">
    <!-- Background -->
    <div class="background">
        {% block background %}{% endblock %}
    </div>

    <!-- Header -->
    <header class="header">
        <img src="{{ resource_config.logo }}" class="logo" alt="{{ resource_config.name }}">
        <h2>{{ resource_config.name }}</h2>
    </header>

    <!-- Main content -->
    <div class="container">
        {% block content %}{% endblock %}
    </div>

    <!-- Global variables for JavaScript -->
    <script>
        window.pageConfig = {
            items: {{ items | tojson }},
            resourceId: "{{ resource_id }}",
            resourceType: "{{ resource_type }}",
            baseUrl: "{{ base_url }}",
            // ...
        };
    </script>

    <!-- JavaScript Libraries -->
    <script src="/static/{app}/js/utils.js?v={version}"></script>
    <script src="/static/{app}/js/main.js?v={version}"></script>
    {% block extra_js %}{% endblock %}
</body>
</html>
```

### 2단계: 관리자 layout.html (Bootstrap 기반)
```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ page_title }} - {{ app_title }}{% endblock %}</title>

    <!-- CSS (로컬 번들링) -->
    <link href="/static/{app}/admin/vendor/bootstrap/bootstrap.min.css" rel="stylesheet">
    <link href="/static/{app}/admin/admin.css" rel="stylesheet">
    <link href="/static/{app}/css/admin/icons.css?v={version}" rel="stylesheet">
    {% block extra_css %}{% endblock %}
</head>
<body>
    <!-- Navigation -->
    <nav class="navbar navbar-expand-lg navbar-light bg-light">
        <div class="container-fluid">
            <a class="navbar-brand" href="/page/{app}/">{{ app_title }}</a>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto">
                    {% for link in nav_links %}
                    <li class="nav-item">
                        <a class="nav-link {% if link.active %}active{% endif %}" href="{{ link.url }}">
                            {{ link.name }}
                        </a>
                    </li>
                    {% endfor %}
                </ul>
            </div>
        </div>
    </nav>

    <!-- Breadcrumb -->
    <nav aria-label="breadcrumb" class="bg-light">
        <div class="container-fluid">
            <ol class="breadcrumb mb-0 py-2">
                <li class="breadcrumb-item"><a href="/page/{app}/">홈</a></li>
                {% block breadcrumb %}
                <li class="breadcrumb-item active">{{ page_title }}</li>
                {% endblock %}
            </ol>
        </div>
    </nav>

    <!-- Main content -->
    <div class="container-fluid py-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <div>
                <h1 class="h3 mb-1">{{ page_title }}</h1>
                <p class="text-muted mb-0">
                    마지막 업데이트: {{ to_kst(generated_at).strftime('%Y-%m-%d %H:%M:%S') }} KST
                </p>
            </div>
            {% block page_actions %}{% endblock %}
        </div>
        {% block content %}{% endblock %}
    </div>

    <!-- JavaScript -->
    <script src="/static/{app}/admin/vendor/bootstrap/bootstrap.bundle.min.js"></script>
    <script src="/static/{app}/admin/vendor/chartjs/chart.min.js"></script>
    <script src="/static/{app}/admin/admin.js"></script>
    {% block extra_js %}{% endblock %}

    <!-- Auto refresh -->
    {% if auto_refresh_interval %}
    <script>
        setTimeout(() => location.reload(), {{ auto_refresh_interval }} * 1000);
    </script>
    {% endif %}
</body>
</html>
```

### 3단계: 페이지 템플릿
```html
{% extends "admin/layout.html" %}

{% block content %}
<div class="row">
    <div class="col-12">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0">제목</h5>
                <span class="badge bg-primary">{{ total_count }}개</span>
            </div>
            <div class="card-body">
                <div id="dataContainer">
                    <div class="text-center py-4">
                        <div class="spinner-border text-primary"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script>
    const PAGE_CONFIG = {
        baseUrl: "/api/v1/{app}",
        // ...
    };
</script>
<script src="/static/{app}/js/{feature}.js?v={version}"></script>
{% endblock %}
```

---

## CSS 구조 규칙

### layers.css - CSS Layer 정의
```css
/* CSS Cascade Layers 우선순위 정의 */
@layer base, layout, components, utilities, themes, animations;
```

### base.css - CSS 변수 및 기본 스타일
```css
@layer base {
    :root {
        /* Primary Colors */
        --primary-color: #3498db;
        --primary-dark: #2980b9;
        --primary-light: rgba(52, 152, 219, 0.1);

        /* Semantic Colors */
        --success-color: #27ae60;
        --warning-color: #f39c12;
        --error-color: #e74c3c;
        --info-color: #17a2b8;

        /* Background Colors */
        --bg-color: #f5f6fa;
        --card-bg: #ffffff;
        --panel-bg: #ffffff;

        /* Text Colors */
        --text-color: #2c3e50;
        --text-muted: #7f8c8d;

        /* Border & Shadow */
        --border-color: #dcdde1;
        --shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        --radius: 8px;
    }

    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        background-color: var(--bg-color);
        color: var(--text-color);
    }
}
```

### themes/{resource_type}.css - 리소스 타입별 테마
```css
@layer themes {
    .type-a-theme {
        --theme-color: #3498db;
        --theme-gradient: linear-gradient(135deg, #3498db, #2980b9);
    }

    .type-b-theme {
        --theme-color: #e74c3c;
        --theme-gradient: linear-gradient(135deg, #e74c3c, #c0392b);
    }
}
```

---

## JS 구조 규칙

### 페이지별 JS 패턴
```javascript
/**
 * {Feature} Page
 * /{resource_type}/path
 */

(function() {
    'use strict';

    // Config from template
    const config = window.pageConfig || {};

    // State
    let currentPage = 1;

    // Render functions
    function renderList(items) {
        const container = document.getElementById('itemList');
        if (!items?.length) {
            container.innerHTML = '<div class="empty-state">데이터가 없습니다</div>';
            return;
        }
        container.innerHTML = items.map(item => `
            <div class="item-card">
                <div class="item-name">${escapeHtml(item.name)}</div>
            </div>
        `).join('');
    }

    // API calls
    async function loadData() {
        try {
            const response = await fetch(`/api/v1/{app}/endpoint`);
            const data = await response.json();
            renderList(data.items);
        } catch (err) {
            console.error('Load failed:', err);
        }
    }

    // Events
    function bindEvents() {
        document.getElementById('refreshBtn')?.addEventListener('click', loadData);
    }

    // Init
    function init() {
        bindEvents();
        loadData();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
```

### utils.js - 공통 유틸리티
```javascript
function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('ko-KR');
}

function formatFileSize(bytes) {
    if (!bytes) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes, unitIdx = 0;
    while (size >= 1024 && unitIdx < units.length - 1) {
        size /= 1024; unitIdx++;
    }
    return `${size.toFixed(1)} ${units[unitIdx]}`;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function showLoading(containerId) {
    document.getElementById(containerId).innerHTML =
        '<div class="loading">Loading...</div>';
}

function showError(message, containerId) {
    document.getElementById(containerId).innerHTML =
        `<div class="error-state">${escapeHtml(message)}</div>`;
}
```

---

## 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser                                  │
├─────────────────────────────────────────────────────────────────┤
│  1. GET /{resource_type}/{id} 또는 /page/{app}/{feature}        │
│     → Page Router → Jinja2 → HTML (정적 레이아웃)               │
│                                                                  │
│  2. DOMContentLoaded → {feature}.js init()                      │
│     → fetch('/api/v1/{app}/endpoint')                           │
│     → renderList(data) → DOM 업데이트                           │
│                                                                  │
│  3. User Action (click, submit)                                 │
│     → fetch('/api/v1/{app}/endpoint', {method: 'POST'})         │
│     → loadData() → 목록 갱신                                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         Server                                   │
├─────────────────────────────────────────────────────────────────┤
│  Page Router (GET only)                                         │
│  ├─ Admin: /page/{app}/* → templates/admin/*.html               │
│  └─ Client: /{resource_type}/* → templates/client/*.html        │
│                                                                  │
│  API Router (CRUD)                                              │
│  └─ /api/v1/{app}/* → JSON 응답 (동적 데이터)                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 버전 관리 (캐시 버스팅)

### 규칙
- CSS/JS 파일 URL에 `?v={version}` 쿼리 파라미터 추가
- 버전 형식: `YYYYMMDD` 또는 `YYYYMMDDx` (당일 여러 번 변경 시)

```html
<link rel="stylesheet" href="/static/{app}/css/base.css?v=20251230">
<script src="/static/{app}/js/main.js?v=20251230a"></script>
```

---

## 체크리스트

### 새 Admin 페이지 추가
```
□ src/application/interface/pages/admin/{feature}.py 생성
□ admin/__init__.py에 라우터 include 추가
□ templates/admin/{feature}.html 생성
□ common.py의 get_nav_links()에 메뉴 추가
□ 필요시 static/{app}/js/{feature}.js 생성
□ 필요시 static/{app}/css/admin/{feature}.css 생성
```

### 새 Client 페이지/테마 추가
```
□ client_page.py에 라우터 함수 추가 (또는 RESOURCE_CONFIGS에 설정 추가)
□ templates/client/{template}.html 생성 (또는 기존 템플릿 재사용)
□ static/{app}/css/themes/{theme}.css 생성
□ base.html의 테마 폴백 확인
```

### API 연동
```
□ 페이지 JS에서 fetch('/api/v1/{app}/endpoint') 사용
□ 로딩/에러/빈 상태 처리
□ API 응답 형식에 맞게 렌더링
```

---

## 금지 사항

| 금지 | 이유 | 대안 |
|------|------|------|
| Page Router에서 POST/PUT/DELETE | 역할 분리 위반 | API Router 사용 |
| Template에서 직접 DB 조회 | 보안/성능 문제 | Domain 서비스 통해 조회 |
| 인라인 스타일/스크립트 | 유지보수 어려움 | CSS/JS 파일 분리 |
| JS에서 하드코딩된 API URL | 변경 어려움 | window.pageConfig 또는 상수 사용 |
| CSS 하드코딩 색상 | 테마 변경 어려움 | CSS 변수 사용 |
| Template에서 복잡한 로직 | Jinja 템플릿 복잡화 | JS에서 처리 |

---

## 참고: 라우터 등록 순서

```python
# main.py에서 라우터 등록 순서 중요!

# 1. Admin pages (specific routes: /page/{app}/*)
app.include_router(admin_router)

# 2. Client pages (generic routes: /{resource_type}/*)
app.include_router(client_router)

# ⚠️ Admin이 먼저 등록되어야 /{resource_type}/* 패턴과 충돌 방지
```

---

## 용어 매핑 (프로젝트별 적용)

| 일반 용어 | 예시 (QR 프로젝트) | 예시 (이커머스) |
|----------|-------------------|----------------|
| `{app}` | `qr` | `shop` |
| `{resource_type}` | `pixai`, `donation` | `product`, `order` |
| `{resource_id}` | `group_id` | `product_id` |
| `/page/{app}/` | `/page/qr/` | `/page/shop/` |
| `client_page.py` | `service_page.py` | `product_page.py` |
| `RESOURCE_CONFIGS` | `SERVICE_CONFIGS` | `CATEGORY_CONFIGS` |

> **참고**: API Router, 도메인 서비스, 어댑터 관련 상세 구조는 `fastapi-api-server-structure` 스킬을 참조하세요. 레이어 의존성 분석은 `layer-optimize` 스킬을 참조하세요.
