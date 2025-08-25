# api/routers/line_bot_rag_integrated.py - 最小限修正版
# 重複登録防止とエラー回避

import logging
from fastapi import APIRouter
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(tags=["line-rag-integrated"])

# ⚠️ このファイルは main.py で LINE_BOT_MODE=rag_integrated の時のみ使用されます
# 通常は line_bot_ultra_fast.py が使用されます

# 最小限の健全性チェックエンドポイントのみ提供
@router.get("/health")
def rag_integrated_health():
    """RAG統合モード健全性チェック"""
    return {
        "status": "available_but_inactive",
        "message": "This router is available but not active. Using ultra_fast mode.",
        "mode": "rag_integrated",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def rag_integrated_debug():
    """RAG統合モードデバッグ情報"""
    return {
        "mode": "rag_integrated",
        "active": False,
        "message": "RAG integrated mode available but not currently active",
        "recommended_mode": "ultra_fast",
        "timestamp": datetime.now().isoformat()
    }

# Webhook は main.py の選択に従って登録される
# このファイル単独では Webhook を登録しない（重複防止）

logger.info("📋 LINE RAG Integrated module loaded (inactive mode)")
