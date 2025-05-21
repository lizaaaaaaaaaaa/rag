from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional, Dict, Any

router = APIRouter()

# グローバルな履歴リスト（まずはメモリ保存。後でDBに切り替え可能！）
history_logs = []

@router.get("/", summary="チャット履歴一覧取得", response_description="チャット履歴リスト")
async def get_history(
    tag: Optional[str] = Query(None, description="タグで絞り込み（省略可）"),
    user_id: Optional[str] = Query(None, description="ユーザーID（省略可、認証後は自動付与予定）"),
) -> Dict[str, Any]:
    try:
        # 今はDBなしなのでメモリ履歴から返す（DB連携時はget_chat_logsに切り替え！）
        logs = history_logs
        # ↓本番はここをフィルタ処理に（今は全件返すだけ）
        return {"logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

