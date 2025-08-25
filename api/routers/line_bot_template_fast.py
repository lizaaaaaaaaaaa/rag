# api/routers/line_bot_template_fast.py - 修正版（条件付き無効化）
"""
このファイルは重複メッセージ防止のため条件付き無効化されています。
template_only モードの時のみ有効になります。
"""

import logging
import os
from fastapi import APIRouter
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(tags=["line-template-fast"])

# 環境変数でモード確認
LINE_BOT_MODE = os.getenv("LINE_BOT_MODE", "ultra_fast_financial")

@router.get("/health")
def template_fast_health():
    """テンプレート高速モード健全性チェック"""
    is_active = LINE_BOT_MODE == "template_only"
    
    return {
        "status": "active" if is_active else "inactive",
        "message": "Template fast mode" if is_active else "This router is inactive to prevent duplicate messages",
        "mode": "template_only",
        "current_active_mode": LINE_BOT_MODE,
        "webhook_registered": is_active,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def template_fast_debug():
    """テンプレート高速モードデバッグ情報"""
    is_active = LINE_BOT_MODE == "template_only"
    
    return {
        "mode": "template_only",
        "active": is_active,
        "current_mode": LINE_BOT_MODE,
        "message": "Template fast mode active" if is_active else "Inactive to prevent duplicates",
        "recommended_mode": "ultra_fast_financial", 
        "duplicate_prevention": True,
        "timestamp": datetime.now().isoformat()
    }

# テンプレート応答クラス（条件付き有効）
class TemplateFastResponder:
    def __init__(self):
        self.active = LINE_BOT_MODE == "template_only"
        
    def get_instant_response(self, message_text: str, user_id: str = "unknown"):
        if not self.active:
            return {
                "response": "このモードは重複防止のため非アクティブです。ultra_fast_financial モードを使用してください。",
                "success": False,
                "mode": "template_only_inactive"
            }
        
        # テンプレート処理（アクティブ時のみ）
        return {
            "response": "テンプレート応答（アクティブモード）",
            "success": True,
            "mode": "template_only_active"
        }

# グローバルインスタンス
template_responder = TemplateFastResponder()

# Webhook は LINE_BOT_MODE が template_only の場合のみ有効
# main.py で条件付きで登録される

if LINE_BOT_MODE == "template_only":
    logger.info("📋 LINE Template Fast module loaded (active mode)")
else:
    logger.info("📋 LINE Template Fast module loaded (inactive - duplicate prevention)")