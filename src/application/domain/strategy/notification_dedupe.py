# -*- coding: utf-8 -*-
"""
Notification Dedupe - 알림 신선도/서명/중복 억제 캐시

NotificationScheduler에서 분리한 응집 단위:
- 직전 데이터 갱신 결과 기록/조회 (job results)
- 예약 알림 신선도(freshness) 판정
- 페이로드 서명(signature) 생성 및 일자 단위 중복 발송 억제(dedupe)

동작은 기존 NotificationScheduler 내부 구현과 동일하게 보존한다.
"""

import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 한국 시간대 (스케줄러와 동일 값)
KST = ZoneInfo("Asia/Seoul")
NOTIFICATION_UPDATE_MAX_AGE = timedelta(minutes=20)
NOTIFICATION_DEDUPE_TTL = timedelta(hours=6)


class NotificationDedupe:
    """알림 신선도/서명/중복 억제 캐시를 소유하는 응집 단위."""

    def __init__(self) -> None:
        # 기존 NotificationScheduler._last_job_results
        self.job_results: dict[str, dict] = {}
        # 기존 NotificationScheduler._notification_delivery_cache
        self.delivery_cache: dict[str, datetime] = {}

    @staticmethod
    def sanitize_result(value):
        if isinstance(value, dict):
            return {k: NotificationDedupe.sanitize_result(v) for k, v in value.items()}
        if isinstance(value, list):
            return [NotificationDedupe.sanitize_result(v) for v in value[:10]]
        if isinstance(value, tuple):
            return [NotificationDedupe.sanitize_result(v) for v in value[:10]]
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def record_job_result(
        self,
        job_type: str,
        slot_label: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        key = f"{job_type}:{slot_label}"
        payload = {
            "job_type": job_type,
            "slot_label": slot_label,
            "recorded_at": datetime.now(KST).isoformat(),
            "success": bool(result and result.get("success", True)) if error is None else False,
        }
        if result:
            payload["result"] = self.sanitize_result(result)
        if error:
            payload["error"] = error
        self.job_results[key] = payload

    def get_notification_freshness(
        self,
        notification_type: str,
        slot_label: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """예약 알림이 직전 데이터 업데이트 결과를 사용할 수 있는지 확인한다."""
        if slot_label in {"manual", "-"}:
            return {
                "fresh": True,
                "required": False,
                "status": "manual",
                "message": "manual execution does not require a scheduled update result",
            }

        now = now or datetime.now(KST)
        key = f"{notification_type}_data_update:{slot_label}"
        update_result = self.job_results.get(key)
        if not update_result:
            return {
                "fresh": False,
                "required": True,
                "status": "missing",
                "message": f"No {notification_type} data update result for {slot_label}",
            }

        if not update_result.get("success", False):
            return {
                "fresh": False,
                "required": True,
                "status": "failed",
                "message": update_result.get("error") or "Previous data update failed",
            }

        recorded_at_raw = update_result.get("recorded_at")
        try:
            recorded_at = datetime.fromisoformat(str(recorded_at_raw))
        except ValueError:
            return {
                "fresh": False,
                "required": True,
                "status": "invalid_timestamp",
                "message": f"Invalid data update timestamp: {recorded_at_raw}",
            }

        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=KST)
        age_seconds = max((now - recorded_at).total_seconds(), 0.0)
        if age_seconds > NOTIFICATION_UPDATE_MAX_AGE.total_seconds():
            return {
                "fresh": False,
                "required": True,
                "status": "stale",
                "age_seconds": round(age_seconds, 1),
                "message": (
                    f"Data update for {slot_label} is stale " f"({int(age_seconds // 60)}m old)"
                ),
            }

        return {
            "fresh": True,
            "required": True,
            "status": "fresh",
            "age_seconds": round(age_seconds, 1),
            "message": "data update is fresh",
        }

    def build_notification_signature(self, payload: object) -> str:
        normalized = self.normalize_signature_payload(payload)
        encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def normalize_signature_payload(value: object):
        if isinstance(value, dict):
            return {
                str(k): NotificationDedupe.normalize_signature_payload(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [NotificationDedupe.normalize_signature_payload(v) for v in value]
        if isinstance(value, tuple):
            return [NotificationDedupe.normalize_signature_payload(v) for v in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def is_duplicate_notification(
        self,
        notification_type: str,
        slot_label: str,
        signature: str,
        now: datetime | None = None,
    ) -> bool:
        if slot_label in {"manual", "-"}:
            return False
        now = now or datetime.now(KST)
        self.prune_delivery_cache(now)
        key = self.notification_cache_key(notification_type, slot_label, signature, now)
        return key in self.delivery_cache

    def mark_notification_sent(
        self,
        notification_type: str,
        slot_label: str,
        signature: str,
        now: datetime | None = None,
    ) -> None:
        if slot_label in {"manual", "-"}:
            return
        now = now or datetime.now(KST)
        self.prune_delivery_cache(now)
        key = self.notification_cache_key(notification_type, slot_label, signature, now)
        self.delivery_cache[key] = now

    @staticmethod
    def notification_cache_key(
        notification_type: str,
        slot_label: str,
        signature: str,
        now: datetime,
    ) -> str:
        return f"{notification_type}:{slot_label}:{now.date().isoformat()}:{signature}"

    def prune_delivery_cache(self, now: datetime) -> None:
        expired_keys = [
            key
            for key, sent_at in self.delivery_cache.items()
            if now - sent_at > NOTIFICATION_DEDUPE_TTL
        ]
        for key in expired_keys:
            self.delivery_cache.pop(key, None)

    @staticmethod
    def build_skipped_notification_result(
        notification_type: str,
        slot_label: str,
        freshness: dict[str, object],
    ) -> dict[str, object]:
        return {
            "success": False,
            "executed": False,
            "notification_type": notification_type,
            "slot": slot_label,
            "sent": False,
            "skipped": True,
            "skip_reason": freshness.get("message"),
            "freshness": freshness,
        }
