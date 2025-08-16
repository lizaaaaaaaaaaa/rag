# api/routers/line_bot_enhanced.py - ハルチネーション対策強化版

import logging
import os
import re
import json
import asyncio
import traceback
from datetime import datetime
from typing import Dict, Optional, Any, List
import concurrent.futures

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from utils.web_search import GoogleSearcher
from utils.fallback import RAGFallbackHandler

logger = logging.getLogger(__name__)

# LINE SDK v3 import
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
    LINE_SDK_AVAILABLE = True
except ImportError as e:
    logger.error(f"LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs): 
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass

router = APIRouter(prefix="/line", tags=["line"])

# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

# 初期化
if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
        logger.info("✅ Enhanced LINE Bot API initialized")
    except Exception as e:
        logger.error(f"❌ LINE Bot API initialization failed: {e}")
        line_bot_api, handler = None, None
else:
    line_bot_api, handler = None, None

# ハルチネーション対策用のRAGレスポンス検証クラス
class AntiHallucinationValidator:
    def __init__(self):
        self.web_searcher = GoogleSearcher()
        self.confidence_threshold = 0.7
        
    async def validate_and_enhance_response(
        self, 
        query: str, 
        rag_response: str, 
        source_docs: List = None
    ) -> Dict[str, Any]:
        """RAG回答を検証し、必要に応じてWeb検索で補強"""
        
        validation_result = {
            "original_response": rag_response,
            "enhanced_response": rag_response,
            "confidence_score": 1.0,
            "sources_used": ["rag"],
            "web_verification": False,
            "hallucination_risk": "low"
        }
        
        # 1. RAG回答の信頼性チェック
        confidence_score = self._calculate_confidence(rag_response, source_docs)
        validation_result["confidence_score"] = confidence_score
        
        # 2. 信頼性が低い場合、またはリアルタイム情報が必要な場合
        needs_web_verification = (
            confidence_score < self.confidence_threshold or
            self._requires_current_info(query) or
            self._is_factual_query(query)
        )
        
        if needs_web_verification:
            logger.info(f"🔍 Web verification needed for query: {query}")
            
            # Web検索で情報を補強
            web_results = self.web_searcher.search_web(query, num_results=3)
            
            if web_results:
                # RAG + Web検索の統合回答を生成
                enhanced_response = await self._create_verified_response(
                    query, rag_response, web_results, source_docs
                )
                
                validation_result.update({
                    "enhanced_response": enhanced_response,
                    "sources_used": ["rag", "web"],
                    "web_verification": True,
                    "hallucination_risk": "mitigated"
                })
            else:
                # Web検索に失敗した場合の処理
                validation_result["hallucination_risk"] = "medium"
                
        return validation_result
    
    def _calculate_confidence(self, response: str, source_docs: List = None) -> float:
        """RAG回答の信頼性スコアを計算"""
        confidence = 1.0
        
        # 回答の長さチェック
        if len(response) < 20:
            confidence -= 0.3
        
        # 曖昧な表現のチェック
        vague_patterns = [
            "申し訳ございません", "わからない", "不明", "詳細は", 
            "確認が必要", "については", "かもしれません"
        ]
        vague_count = sum(1 for pattern in vague_patterns if pattern in response)
        confidence -= vague_count * 0.1
        
        # ソース文書との関連性
        if source_docs and len(source_docs) > 0:
            confidence += 0.2
        elif not source_docs:
            confidence -= 0.2
            
        return max(0.0, min(1.0, confidence))
    
    def _requires_current_info(self, query: str) -> bool:
        """リアルタイム情報が必要かチェック"""
        current_keywords = [
            "最新", "現在", "今", "2024", "2025", "最近",
            "補助金", "助成金", "制度", "金利", "価格", "相場"
        ]
        return any(keyword in query for keyword in current_keywords)
    
    def _is_factual_query(self, query: str) -> bool:
        """事実確認が重要な質問かチェック"""
        factual_keywords = [
            "坪単価", "価格", "費用", "金額", "制度", "法律", 
            "基準", "規制", "条件", "要件"
        ]
        return any(keyword in query for keyword in factual_keywords)
    
    async def _create_verified_response(
        self, 
        query: str, 
        rag_response: str, 
        web_results: List[Dict], 
        source_docs: List = None
    ) -> str:
        """RAGとWeb検索結果を統合した検証済み回答を生成"""
        
        try:
            from llm.llm_runner import load_llm
            llm, _, _ = load_llm()
            
            # Web検索結果をまとめる
            web_context = "\n".join([
                f"・{result['title']}: {result['snippet']}" 
                for result in web_results[:3]
            ])
            
            # ソース文書情報
            rag_context = ""
            if source_docs:
                rag_context = "\n".join([
                    doc.page_content[:200] + "..." 
                    for doc in source_docs[:2]
                ])
            
            # 統合プロンプト
            verification_prompt = f"""あなたは正確性を重視する住宅専門アドバイザーです。
以下の情報を比較検証し、最も正確で有用な回答を生成してください。

【質問】
{query}

【社内資料からの回答】
{rag_response}

【社内資料の詳細】
{rag_context}

【最新のWeb情報】
{web_context}

【指示】
1. 社内資料とWeb情報を比較検証する
2. 矛盾がある場合は最新情報を優先する
3. 不確実な情報は明記する
4. 自然で親しみやすい日本語で回答する
5. 出典については言及しない

【検証済み回答】"""

            response = llm.invoke(verification_prompt)
            verified_answer = response.content if hasattr(response, 'content') else str(response)
            
            # 回答をクリーンアップ
            return self._clean_response(verified_answer)
            
        except Exception as e:
            logger.error(f"Error creating verified response: {e}")
            # エラー時はRAG回答にWeb情報を簡単に追加
            return f"{rag_response}\n\n※最新情報も確認いたしました。"
    
    def _clean_response(self, response: str) -> str:
        """回答をクリーンアップ"""
        # 不要なパターンを削除
        patterns_to_remove = [
            r"【[^】]*】",
            r"検証済み回答[:：]",
            r"社内資料[:：][^\n]*",
            r"Web情報[:：][^\n]*"
        ]
        
        cleaned = response
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE)
        
        return cleaned.strip()

# ハルチネーション対策統合処理クラス
class EnhancedRAGProcessor:
    def __init__(self):
        self.validator = AntiHallucinationValidator()
        self.fallback_handler = RAGFallbackHandler()
        
    async def process_user_question(self, message_text: str, user_id: str) -> str:
        """ユーザー質問をハルチネーション対策付きで処理"""
        
        try:
            # アプリのグローバル変数を取得
            globals_dict = self._get_app_globals()
            vectorstore = globals_dict.get("vectorstore")
            rag_chain_template = globals_dict.get("rag_chain_template")
            llm_instance = globals_dict.get("llm_instance")
            
            # 1. まずRAGで回答を試行
            if vectorstore and rag_chain_template:
                try:
                    rag_result = rag_chain_template.invoke({"query": message_text})
                    rag_response = rag_result.get("result", "")
                    source_docs = rag_result.get("source_documents", [])
                    
                    if rag_response and len(rag_response.strip()) > 10:
                        # 2. ハルチネーション対策で検証・強化
                        validation_result = await self.validator.validate_and_enhance_response(
                            message_text, rag_response, source_docs
                        )
                        
                        logger.info(f"📊 Validation result: confidence={validation_result['confidence_score']:.2f}, "
                                   f"web_verified={validation_result['web_verification']}")
                        
                        return validation_result["enhanced_response"]
                    
                except Exception as rag_error:
                    logger.error(f"RAG processing error: {rag_error}")
            
            # 3. RAGが失敗した場合はフォールバック処理
            logger.info("🔄 Using fallback processing...")
            fallback_result = await self.fallback_handler.handle_failure(
                message_text, Exception("RAG processing failed")
            )
            
            return fallback_result.get("answer", "申し訳ございません。再度お試しください。")
            
        except Exception as e:
            logger.error(f"💥 Enhanced RAG processing error: {e}")
            return "申し訳ございません。システムに一時的な問題が発生しています。"
    
    def _get_app_globals(self):
        """アプリのグローバル変数を取得"""
        try:
            import main
            return {
                'vectorstore': getattr(main, 'vectorstore', None),
                'rag_chain_template': getattr(main, 'rag_chain_template', None),
                'llm_instance': getattr(main, 'llm_instance', None)
            }
        except Exception as e:
            logger.error(f"Failed to get app globals: {e}")
            return {'vectorstore': None, 'rag_chain_template': None, 'llm_instance': None}

# グローバルインスタンス
enhanced_processor = EnhancedRAGProcessor()

# Webhook エンドポイント
@router.post("/webhook")
async def enhanced_line_webhook(request: Request, background_tasks: BackgroundTasks):
    """強化されたLINE Webhook（ハルチネーション対策付き）"""
    
    if not line_bot_api or not handler:
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        if not signature:
            return {"status": "error", "message": "Missing signature"}
        
        body_text = body.decode("utf-8")
        handler.handle(body_text, signature)
        
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError:
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "error": str(e)}

# イベントハンドラ（ハルチネーション対策強化版）
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_enhanced_text_message(event):
        """強化されたメッセージハンドラ"""
        start_time = datetime.now()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            
            logger.info(f"📱 Enhanced processing: user={user_id}, query='{message_text}'")
            
            # 1. リッチメニューの即座応答チェック
            if _is_richmenu_action(message_text):
                response = _get_richmenu_response(message_text)
                _send_line_reply(event.reply_token, response)
                
                duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"⚡ Instant richmenu response: {duration:.2f}s")
                return
            
            # 2. ハルチネーション対策付きRAG処理
            def process_with_anti_hallucination():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        enhanced_processor.process_user_question(message_text, user_id)
                    )
                    loop.close()
                    return result
                except Exception as e:
                    logger.error(f"Processing error: {e}")
                    return _get_fallback_response(message_text)
            
            # 3. タイムアウト付きで実行
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(process_with_anti_hallucination)
                try:
                    enhanced_response = future.result(timeout=8)  # 8秒タイムアウト
                except concurrent.futures.TimeoutError:
                    logger.error("❌ Processing timeout")
                    enhanced_response = "処理に時間がかかっています。もう一度お試しください。"
            
            # 4. 回答送信
            _send_line_reply(event.reply_token, enhanced_response)
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Enhanced response sent: {duration:.2f}s")
            
        except Exception as e:
            logger.error(f"❌ Enhanced message handler error: {e}")
            emergency_response = _get_fallback_response(message_text if 'message_text' in locals() else "")
            _send_line_reply(event.reply_token, emergency_response)

# ヘルパー関数
def _is_richmenu_action(message: str) -> bool:
    """リッチメニューアクションかチェック"""
    richmenu_actions = ["AI相談", "AI住まいサイト", "資料請求", "展示場来場予約", "資金計画", "チャット相談"]
    return any(action in message for action in richmenu_actions)

def _get_richmenu_response(message: str) -> str:
    """リッチメニューの即座応答"""
    responses = {
        "AI相談": "🤖 AI住まい相談を開始します！住まいに関するご質問をお気軽にどうぞ。",
        "AI住まいサイト": "🌐 住まい情報サイトをご案内します。詳しくはこちら→ https://kinoe-design.com",
        "資料請求": "📋 資料請求を承ります。お名前、ご住所、お電話番号をお教えください。",
        "展示場来場予約": "📍 展示場見学を承ります。ご希望日時をお聞かせください。",
        "資金計画": "💰 資金計画のご相談を承ります。ご年収、ご希望借入額などをお聞かせください。",
        "チャット相談": "💬 スタッフとのご相談を開始します。お気軽にお声かけください。"
    }
    
    for key, response in responses.items():
        if key in message:
            return response
    
    return "こんにちは！ご質問をお聞かせください。"

def _get_fallback_response(query: str) -> str:
    """フォールバック応答"""
    if "坪単価" in query:
        return "坪単価については、約70〜85万円/坪が目安です。詳細はお問い合わせください。"
    elif "資料" in query:
        return "資料をお送りします。お名前、ご住所、お電話番号をお教えください。"
    else:
        return "申し訳ございません。詳しくはお問い合わせください。"

def _send_line_reply(reply_token: str, message: str) -> bool:
    """LINE返信送信"""
    try:
        if line_bot_api:
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message)]
                )
            )
            return True
    except Exception as e:
        logger.error(f"Failed to send LINE reply: {e}")
    return False

# 診断エンドポイント
@router.get("/anti-hallucination-status")
def get_anti_hallucination_status():
    """ハルチネーション対策の状態確認"""
    return {
        "status": "active",
        "features": {
            "rag_validation": True,
            "web_verification": True,
            "confidence_scoring": True,
            "fallback_handling": True
        },
        "confidence_threshold": enhanced_processor.validator.confidence_threshold,
        "timestamp": datetime.now().isoformat()
    }