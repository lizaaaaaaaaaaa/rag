# api/routers/line_bot_rag_integrated.py - 修正版（条件付き無効化）
"""
このファイルは重複メッセージ防止のため条件付き無効化されています。
ultra_fast モードの時のみ有効になります。
"""

import logging
import os
from fastapi import APIRouter
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(tags=["line-rag-integrated"])

# 環境変数でモード確認
LINE_BOT_MODE = os.getenv("LINE_BOT_MODE", "ultra_fast_financial")

@router.get("/health")
def rag_integrated_health():
    """RAG統合モード健全性チェック"""
    is_active = LINE_BOT_MODE == "rag_integrated"
    
    return {
        "status": "active" if is_active else "inactive",
        "message": "RAG integrated mode" if is_active else "This router is inactive to prevent duplicate messages",
        "mode": "rag_integrated",
        "current_active_mode": LINE_BOT_MODE,
        "webhook_registered": is_active,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def rag_integrated_debug():
    """RAG統合モードデバッグ情報"""
    is_active = LINE_BOT_MODE == "rag_integrated"
    
    return {
        "mode": "rag_integrated",
        "active": is_active,
        "current_mode": LINE_BOT_MODE,
        "message": "RAG integrated mode active" if is_active else "Inactive to prevent duplicates",
        "recommended_mode": "ultra_fast_financial",
        "duplicate_prevention": True,
        "timestamp": datetime.now().isoformat()
    }

# Webhook は LINE_BOT_MODE が rag_integrated の場合のみ有効
# main.py で条件付きで登録される

if LINE_BOT_MODE == "rag_integrated":
    logger.info("📋 LINE RAG Integrated module loaded (active mode)")
else:
    logger.info("📋 LINE RAG Integrated module loaded (inactive - duplicate prevention)")