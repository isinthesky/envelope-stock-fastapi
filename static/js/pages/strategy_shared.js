// Shared utilities for strategy subpages (manage/operate/edit/states/signals)
// - strategy_id resolution: query param SSOT, optional localStorage fallback
// - localStorage schema + TTL (24h)
// - navigation helpers

(function () {
  const STORAGE_KEY_V1 = 'strategy.selected.v1';
  const LEGACY_KEY = 'buyStrategy.selectedStrategyId';
  const TTL_SECONDS = 24 * 60 * 60;

  const nowSec = () => Math.floor(Date.now() / 1000);

  const parsePositiveInt = (raw) => {
    if (raw == null) return null;
    const s = String(raw).trim();
    // fail-close: only accept strict positive integer strings
    if (!/^[1-9][0-9]*$/.test(s)) return null;
    const n = Number(s);
    if (!Number.isSafeInteger(n) || n <= 0) return null;
    return n;
  };

  const escapeHtml = (s) => {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  };

  const readJsonSafely = async (res) => {
    try {
      const data = await res.json();
      if (!res.ok) {
        return { ok: false, data: { ...data, status: res.status, success: data?.success ?? false } };
      }
      return { ok: true, data };
    } catch (e) {
      return {
        ok: false,
        data: { success: false, status: res.status, detail: 'JSON 파싱 실패' },
      };
    }
  };

  const extractStrategy = (payload) => {
    if (!payload) return null;
    // ResponseDTO[StrategyDetailResponseDTO]
    if (payload.data?.strategy) return payload.data.strategy;
    if (payload.data?.id) return payload.data;
    if (payload.strategy) return payload.strategy;
    if (payload.id) return payload;
    return null;
  };

  const persistSelection = ({ id, account_no }) => {
    const strategyId = parsePositiveInt(id);
    if (!strategyId) {
      clearSelection();
      return;
    }

    const value = {
      id: strategyId,
      account_no: account_no || null,
      updated_at: nowSec(),
    };

    try {
      localStorage.setItem(STORAGE_KEY_V1, JSON.stringify(value));
      // Backward compatibility (best effort)
      localStorage.setItem(LEGACY_KEY, String(strategyId));
    } catch (e) {
      // ignore
    }
  };

  const clearSelection = () => {
    try {
      localStorage.removeItem(STORAGE_KEY_V1);
      localStorage.removeItem(LEGACY_KEY);
    } catch (e) {
      // ignore
    }
  };

  const loadSelection = () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY_V1);
      if (raw) {
        const parsed = JSON.parse(raw);
        const id = parsePositiveInt(parsed?.id);
        const updatedAt = parsePositiveInt(parsed?.updated_at);
        if (!id || !updatedAt) {
          clearSelection();
          return null;
        }
        if (nowSec() - updatedAt > TTL_SECONDS) {
          clearSelection();
          return null;
        }
        return { id, account_no: parsed?.account_no || null, updated_at: updatedAt };
      }

      // legacy fallback (no TTL)
      const legacy = localStorage.getItem(LEGACY_KEY);
      const legacyId = parsePositiveInt(legacy);
      return legacyId ? { id: legacyId, account_no: null, updated_at: nowSec() } : null;
    } catch (e) {
      return null;
    }
  };

  const getQueryStrategyId = () => {
    const params = new URLSearchParams(window.location.search || '');
    if (!params.has('strategy_id')) return { hasParam: false, id: null, raw: null };
    const raw = params.get('strategy_id');
    const id = parsePositiveInt(raw);
    return { hasParam: true, id, raw };
  };

  // Resolve strategy_id for a page.
  // - If query param exists: treat as SSOT. Invalid query => fail-close (no localStorage fallback)
  // - If query param absent: allow localStorage fallback
  const resolveStrategyId = () => {
    const q = getQueryStrategyId();
    if (q.hasParam) {
      return { id: q.id, source: 'query', queryRaw: q.raw, allowStorageFallback: false };
    }
    const stored = loadSelection();
    return { id: stored?.id || null, source: stored ? 'storage' : 'none', allowStorageFallback: true };
  };

  const buildUrl = (path, strategyId) => {
    const id = parsePositiveInt(strategyId);
    return id ? `${path}?strategy_id=${encodeURIComponent(String(id))}` : path;
  };

  const setText = (el, msg) => {
    if (!el) return;
    el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
  };

  // Validate strategy_id by calling GET /api/v1/strategies/{id}
  const validateStrategyId = async (strategyId) => {
    const id = parsePositiveInt(strategyId);
    if (!id) return { ok: false, error: { detail: 'invalid strategy_id' } };

    try {
      const res = await fetch(`/api/v1/strategies/${id}`);
      const parsed = await readJsonSafely(res);
      const dto = parsed.data;
      const ok = parsed.ok && (dto?.success ?? true) && !!extractStrategy(dto);
      if (!ok) {
        return { ok: false, error: dto };
      }
      return { ok: true, strategy: extractStrategy(dto), dto };
    } catch (e) {
      return { ok: false, error: { success: false, detail: e.message } };
    }
  };

  window.StrategyShared = {
    STORAGE_KEY_V1,
    LEGACY_KEY,
    TTL_SECONDS,
    parsePositiveInt,
    escapeHtml,
    readJsonSafely,
    extractStrategy,
    persistSelection,
    clearSelection,
    loadSelection,
    getQueryStrategyId,
    resolveStrategyId,
    buildUrl,
    setText,
    validateStrategyId,
  };
})();
