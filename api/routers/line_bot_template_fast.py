# api/routers/line_bot_template_fast.py - 最小限修正版
# 重複登録防止とエラー回避

import logging
from fastapi import APIRouter
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(tags=["line-template-fast"])

# ⚠️ このファイルは main.py で LINE_BOT_MODE=template_only の時のみ使用されます

# 最小限の健全性チェックエンドポイントのみ提供
@router.get("/health")
def template_fast_health():
    """テンプレート高速モード健全性チェック"""
    return {
        "status": "available_but_inactive",
        "message": "This router is available but not active. Using ultra_fast mode.",
        "mode": "template_only",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def template_fast_debug():
    """テンプレート高速モードデバッグ情報"""
    return {
        "mode": "template_only",
        "active": False,
        "message": "Template fast mode available but not currently active",
        "recommended_mode": "ultra_fast",
        "timestamp": datetime.now().isoformat()
    }

# テンプレート応答クラス（参照用のみ、実際には ultra_fast で統合）
class TemplateFastResponder:
    def get_instant_response(self, message_text: str, user_id: str = "unknown"):
        return {
            "response": "このモードは現在非アクティブです。ultra_fast モードを使用してください。",
            "success": False,
            "mode": "template_only_inactive"
        }

# グローバルインスタンス（参照用）
template_responder = TemplateFastResponder()

# Webhook は main.py の選択に従って登録される
# このファイル単独では Webhook を登録しない（重複防止）

logger.info("📋 LINE Template Fast module loaded (inactive mode)")
