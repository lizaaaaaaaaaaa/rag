# api/routers/reconsent_tasks.py
from fastapi import APIRouter, Header, HTTPException
from datetime import datetime, timedelta, timezone
import os
from typing import Optional, Dict, Any

router = APIRouter(tags=["tasks"])

CRON_SECRET = os.getenv("CRON_SECRET", "set-in-env")
JST = timezone(timedelta(hours=9))


@router.post("/tasks/reconsent")
def reconsent_task(
    x_cron_secret: Optional[str] = Header(None),  # Header "X-Cron-Secret" に対応
) -> Dict[str, Any]:
    """
    期限切れ同意の再通知バッチ用エンドポイント（Cloud Scheduler 等から叩く前提）。
    - 認証: ヘッダ X-Cron-Secret を環境変数 CRON_SECRET と比較（一致しなければ 401）
    - 処理: 同意日時が 12 か月より古いユーザーを抽出してリマインド送信（※実装は TODO）
    - 返却: 実行OK と基準日時 (ISO)
    """
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")

    cutoff = datetime.now(JST) - timedelta(days=365)

    # TODO: あなたのORM/DBに合わせてクエリを実装
    # 例:
    # users = Session.query(Consent.user_id).filter(
    #     Consent.consented_at < cutoff,
    #     Consent.withdrawn == False
    # ).all()
    # for u in users:
    #     send_line_push(u, title="同意更新のお願い", link="/liff/consent")

    return {"ok": True, "cutoff_iso": cutoff.isoformat()}
