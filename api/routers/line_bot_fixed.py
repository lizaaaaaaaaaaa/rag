# api/routers/line_bot_fixed.py - 完全無効化版
"""
このファイルは重複メッセージ問題のため無効化されています。
line_bot_ultra_fast.py を使用してください。
"""

from fastapi import APIRouter
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# 無効化されたルーター
router = APIRouter(tags=["line-bot-fixed-disabled"])

@router.get("/status")
def disabled_fixed_line_bot_status():
    """無効化されたLINE Bot Fixed状態"""
    return {
        "status": "disabled", 
        "reason": "Duplicate message prevention",
        "active_bot": "line_bot_ultra_fast.py",
        "message": "This fixed LINE bot router has been disabled to prevent duplicate messages",
        "timestamp": datetime.now().isoformat()
    }

logger.warning("⚠️ line_bot_fixed.py is DISABLED to prevent duplicate messages")