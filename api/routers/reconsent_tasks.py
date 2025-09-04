# 再同意タスク（Cloud Scheduler 用）
# - ヘッダ "X-Cron-Secret" を検証
# - モード:
#   * mode=daily ... 日次ライフサイクル処理（期限警告・期限切れ処理）
#   * mode=major ... POLICY_VERSION のメジャー更新時、再同意通知（LIFF へ誘導）
# - 速度重視: 実処理はサービスに委譲

from fastapi import APIRouter, Header, HTTPException, Query
from datetime import datetime, date
from typing import Optional, Dict, Any
import os

from api.services.worm_service import EnhancedWORMManager
from services.manifest_service import ManifestService
from services.lifecycle_service import ConsentLifecycleManager

router = APIRouter(tags=["tasks"])

CRON_SECRET = os.getenv("CRON_SECRET", "set-in-env")
PROJECT_ID  = os.getenv("GCP_PROJECT_ID", "your-gcp-project")
JST = "+09:00"

@router.post("/tasks/reconsent")
async def reconsent_task(
    x_cron_secret: Optional[str] = Header(None),
    mode: str = Query("daily", regex="^(daily|major)$"),
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD（省略時は今日）"),
    target_version: Optional[str] = Query(None, description="major更新で通知したい POLICY_VERSION")
) -> Dict[str, Any]:
    """
    期限/バージョンに応じた再同意系のバッチ実行ポイント
    - daily: 期限警告・期限切れ処理（速度重視）
    - major: POLICY_VERSION メジャー更新時の再同意通知
    """
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")

    # 依存サービスの薄い初期化（WORM 管理は health check 程度に利用）
    worm = EnhancedWORMManager.from_env()  # 既存の from_env 実装を想定
    manifest = ManifestService(worm_manager=worm, project_id=PROJECT_ID)
    lifecycle = ConsentLifecycleManager(worm_manager=worm, manifest_service=manifest, project_id=PROJECT_ID)

    if mode == "daily":
        d = date.fromisoformat(target_date) if target_date else date.today()
        result = await lifecycle.process_daily_lifecycle(d)
        return {"mode": "daily", "ok": bool(result.get("success", True)), "result": result, "ts": datetime.now().isoformat() + JST}

    # mode == "major"
    result = await lifecycle.notify_policy_major_update(target_version)
    return {"mode": "major", "ok": True, "result": result, "ts": datetime.now().isoformat() + JST}
