# api/routers/line_bot_enhanced.py - 完全無効化版
"""
このファイルは重複メッセージ問題のため無効化されています。
line_bot_ultra_fast.py を使用してください。
"""

from fastapi import APIRouter
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# 無効化されたルーター
router = APIRouter(tags=["line-bot-enhanced-disabled"])

@router.get("/status")
def disabled_enhanced_line_bot_status():
    """無効化されたLINE Bot Enhanced状態"""
    return {
        "status": "disabled",
        "reason": "Duplicate message prevention",
        "active_bot": "line_bot_ultra_fast.py",
        "message": "This enhanced LINE bot router has been disabled to prevent duplicate messages",
        "timestamp": datetime.now().isoformat()
    }

logger.warning("⚠️ line_bot_enhanced.py is DISABLED to prevent duplicate messages")