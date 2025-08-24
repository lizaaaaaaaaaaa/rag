# api/routers/chat.py - 修正版（文章途切れ対策・処理速度改善）

import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback
import os
import re
import asyncio
import time
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

# 既存のWeb検索ラッパー（必要に応じてフォールバック等で利用）
from utils.web_search import GoogleSearcher as WebSearcher

# LangSmithトレースユーティリティ
from utils.langsmith_tracer import RAGTracer

# ハルチネーション対策の統合機能
try:
    from integration.anti_hallucination_integration import enhance_web_chat_response
    ANTI_HALLUCINATION_AVAILABLE = True
except ImportError:
    ANTI_HALLUCINATION_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Anti-hallucination integration not available")

# traceable の条件付きインポート（本番で未導入でも壊れないように）
try:
    from langsmith import traceable
except ImportError:
    def traceable(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator

router = APIRouter()
history_logs: list[dict] = []

logger = logging.getLogger(__name__)

# ============================================================================
# 高速応答キャッシュシステム
# ============================================================================
_response_cache: Dict[str, Dict[str, Any]] = {}
_cache_stats = {"hits": 0, "misses": 0}
MAX_CACHE_SIZE = 500

def get_cache_key(query: str) -> str:
    """キャッシュキー生成"""
    return query.lower().strip()[:200]

def get_cached_response(query: str) -> Optional[str]:
    """キャッシュから応答を取得"""
    global _cache_stats
    key = get_cache_key(query)
    if key in _response_cache:
        _cache_stats["hits"] += 1
        logger.info(f"💾 Cache HIT: {query[:50]}...")
        return _response_cache[key]["answer"]
    _cache_stats["misses"] += 1
    return None

def cache_response(query: str, answer: str, source: str = "rag"):
    """応答をキャッシュに保存"""
    global _response_cache
    if len(_response_cache) >= MAX_CACHE_SIZE:
        # 古いエントリを削除
        oldest_key = min(_response_cache.keys(), 
                        key=lambda k: _response_cache[k]["timestamp"])
        del _response_cache[oldest_key]
    
    key = get_cache_key(query)
    _response_cache[key] = {
        "answer": answer,
        "source": source,
        "timestamp": time.time()
    }
    logger.info(f"💾 Cache SET: {query[:50]}...")

# ============================================================================
# 高速テンプレート応答システム
# ============================================================================
FAST_TEMPLATES = {
    "坪単価": """坪単価についてご案内いたします。

💰 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望により変動いたします。詳細なお見積りをご希望でしたら、お気軽にお問い合わせください。""",

    "標準仕様": """標準仕様についてご説明いたします。

🏗️ **構造・性能**
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

**設備仕様**
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

より詳しい仕様書をご希望の場合は、資料請求または展示場見学をお申し込みください。""",

    "断熱性能": """断熱性能についてご案内いたします。

🌡️ **断熱等級**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（地域区分6）
・C値：1.0以下（気密性能）

**使用断熱材**
・外壁：高性能グラスウール
・屋根：吹付断熱材
・基礎：押出法ポリスチレンフォーム

**快適性**
・夏涼しく、冬暖かい
・光熱費の削減効果
・結露抑制

詳しくは展示場でご体感いただけます。""",

    "耐震性能": """耐震性能についてご案内いたします。

🏗️ **耐震等級**
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度
・許容応力度計算による構造計算

**構造材**
・構造用集成材使用
・金物工法による強固な接合
・ベタ基礎による堅固な基礎

**保証**
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応

安心・安全な住まいをお約束いたします。""",

    "補助金": """住宅購入時の補助金制度についてご案内します。

💰 **主な補助金制度**

🏠 **ZEH補助金**
高性能住宅への補助
定額55万円～

🌱 **こどもエコすまい支援事業**  
子育て世帯への支援
最大100万円

🏦 **住宅ローン減税**
所得税の控除制度
13年間の減税メリット

📋 **地域独自の補助金**
自治体による支援
地域により異なります

※制度は年度ごとに変更される可能性があります。最新情報はスタッフまでお問い合わせください。""",
}

def get_template_response(query: str) -> Optional[str]:
    """テンプレート応答の取得"""
    query_lower = query.lower()
    
    template_keywords = {
        "坪単価": ["坪単価", "価格", "費用", "いくら", "金額", "コスト", "値段"],
        "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本", "スタンダード"],
        "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "ua値", "c値"],
        "耐震性能": ["耐震", "地震", "耐震性能", "安全", "強度", "構造"],
        "補助金": ["補助金", "助成金", "支援金", "補助制度", "支援制度", "zeh補助"],
    }
    
    for template_key, keywords in template_keywords.items():
        if any(keyword in query_lower for keyword in keywords):
            logger.info(f"🎯 Template match: {template_key}")
            return FAST_TEMPLATES[template_key]
    
    return None

# ============================================================================
# 文章完全性確保システム（強化版）
# ============================================================================
def ensure_complete_response(text: str, query: str = "") -> str:
    """応答の完全性を確保（強化版）"""
    if not text or len(text.strip()) < 5:
        return generate_fallback_response(query)
    
    text = text.strip()
    
    # 文末チェックと補完
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        logger.info(f"🔧 Fixing incomplete response ending with: '{text[-30:]}'")
        
        # 特定の途切れパターンの補完
        if text.endswith('や'):  # 「土地探しや」
            if "土地" in text:
                text += "建築準備を総合的に進めることをお勧めします。"
            else:
                text += "関連する準備を進めることをお勧めします。"
        elif text.endswith('重要'):  # 「重要」
            if "選定" in text:
                text += 'です。詳しい選び方についてはスタッフまでご相談ください。'
            else:
                text += 'なポイントです。詳細についてはお気軽にお問い合わせください。'
        elif text.endswith('必要'):
            text += 'です。'
        elif text.endswith('について'):
            text += 'は、詳細をご案内いたします。'
        elif text.endswith('選定') or text.endswith('検討'):
            text += 'も重要な要素です。'
        elif text.endswith('確認') or text.endswith('準備'):
            text += 'を進めることをお勧めします。'
        elif text.endswith('計画') or text.endswith('設計'):
            text += 'が成功の鍵となります。'
        elif text.endswith('性能') or text.endswith('品質'):
            text += 'にこだわっています。'
        elif text.endswith('対応') or text.endswith('仕様'):
            text += 'となっております。'
        elif text.endswith('条件') or text.endswith('基準'):
            text += 'を満たしています。'
        elif text.endswith('など'):
            text += 'があります。'
        elif text.endswith('から'):
            text += '始めることをお勧めします。'
        elif text.endswith('また'):
            text += '、詳細についてはお問い合わせください。'
        elif text.endswith('ます') or text.endswith('です'):
            text += '。'
        elif text.endswith('た') or text.endswith('る'):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif text.endswith('は') or text.endswith('が'):
            text += '重要です。'
        elif text.endswith('ので') or text.endswith('ため'):
            text += '、お気軽にご相談ください。'
        else:
            # 長さによる補完
            if len(text) > 50:
                text += '。'
            elif len(text) > 25:
                text += '。詳しくはお問い合わせください。'
            else:
                text = generate_fallback_response(query)
        
        logger.info(f"✅ Fixed response now ends with: '{text[-30:]}'")
    
    return text

def generate_fallback_response(query: str) -> str:
    """フォールバック応答の生成"""
    q_lower = query.lower()
    
    if "坪単価" in q_lower or "価格" in q_lower:
        return "坪単価については、お客様のご希望される仕様や設備によって異なります。標準仕様では約70〜85万円/坪が目安となりますが、詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。"
    elif "仕様" in q_lower:
        return "住宅の仕様について詳しくご案内いたします。耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。"
    elif "家を建てる" in q_lower or "マイホーム" in q_lower:
        return "家づくりを始める際は、まず予算の確認、希望する間取りや設備の整理、土地の条件確認から始めることをお勧めします。信頼できる建築会社の選定も重要なポイントです。お客様のご要望をお聞かせいただければ、最適なプランをご提案いたします。"
    else:
        return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。スタッフ一同、お客様の理想の住まいづくりをお手伝いいたします。"

# ============================================================================
# リクエストモデル
# ============================================================================
class ChatRequest(BaseModel):
    question: str
    username: str | None = None

def is_general_greeting_or_chat(query: str) -> bool:
    """一般的な挨拶・雑談判定"""
    greetings = [
        "こんにちは", "こんばんは", "おはよう", "はじめまして",
        "hello", "hi", "hey", "ありがとう", "さようなら",
        "元気", "調子はどう", "お疲れ様", "よろしく"
    ]
    query_lower = query.lower()
    for greeting in greetings:
        if greeting in query_lower:
            return True
    if len(query.strip()) <= 5:
        return True
    question_words = ["何", "どう", "いつ", "どこ", "誰", "なぜ", "どんな", "どの", "？", "?"]
    has_question = any(word in query for word in question_words)
    if len(query) <= 20 and not has_question:
        return True
    return False

def get_general_response_from_llm(query: str, llm_instance):
    """LLMからの一般応答取得"""
    try:
        prompt = f"""あなたは親切で丁寧な日本語のAIアシスタントです。
以下のユーザーの入力に対して、自然で親しみやすい日本語で応答してください。
技術的な内容ではなく、一般的な会話として応答してください。

ユーザー: {query}

アシスタント:"""
        if hasattr(llm_instance, 'invoke'):
            response = llm_instance.invoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        else:
            response = llm_instance(prompt)
            return response if isinstance(response, str) else str(response)
    except Exception as e:
        logger.error(f"Error generating general response: {e}")
        if "こんにちは" in query:
            return "こんにちは！今日はどのようなご用件でしょうか？お手伝いできることがあれば、お気軽にお尋ねください。"
        elif "ありがとう" in query:
            return "どういたしまして！他にもご質問がございましたら、いつでもお聞きください。"
        else:
            return "申し訳ございません。もう一度お聞かせいただけますか？"

def clean_rag_response(raw_response: str) -> str:
    """RAG回答をクリーンアップして自然な形式に変換（大幅改良版）"""
    if not raw_response or len(raw_response.strip()) < 3:
        return "申し訳ございません。お尋ねの内容について詳細な情報が見つかりませんでした。"

    cleaned = raw_response

    # 構造化・出典表記などの除去
    structure_patterns = [
        r"関連文書が見つかりました[:：]?\s*",
        r"関連情報が見つかりました[:：]?\s*",
        r"\d+\.\s*【質問】[^】]*】\s*",
        r"【回答】\s*",
        r"【質問】\s*",
        r"出典[:：]\s*[^\n]*",
        r"/tmp/tmp[a-zA-Z0-9_]*\.pdf",
        r"\([pP]\d+\)",
        r"^\d+\.\s*",
        r"【[^】]*】",
        r"^質問[:：]\s*",
        r"^回答[:：]\s*",
        r"出典[:：][^\n]*",
        r"\.pdf\s*\([pP]\d+\)",
        r"\.pdf\s+\(p\d+\)",
    ]
    for pattern in structure_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

    # 縦書き由来の分断行を連結
    lines = cleaned.split('\n')
    fixed_lines = []
    char_buffer = []
    for line in lines:
        line = line.strip()
        if not line:
            if char_buffer:
                combined = ''.join(char_buffer)
                if len(combined) > 2:
                    fixed_lines.append(combined)
                char_buffer = []
            continue
        if len(line) <= 3:
            char_buffer.append(line)
        else:
            if char_buffer:
                combined = ''.join(char_buffer)
                if len(combined) > 2:
                    fixed_lines.append(combined)
                char_buffer = []
            fixed_lines.append(line)
    if char_buffer:
        combined = ''.join(char_buffer)
        if len(combined) > 2:
            fixed_lines.append(combined)

    # 重複行の排除
    unique_content = []
    seen_content = set()
    for line in fixed_lines:
        if len(line) < 5:
            continue
        line_normalized = re.sub(r'[。、\s]', '', line.lower())
        if any(line_normalized in s or s in line_normalized for s in seen_content):
            continue
        seen_content.add(line_normalized)
        unique_content.append(line)

    # 一番意味のある行を採用し整形
    if unique_content:
        result = max(unique_content, key=len)
        result = re.sub(r'\s+', ' ', result)
        result = re.sub(r'([。！？])\s*', r'\1', result).strip()
    else:
        result = "申し訳ございません。お尋ねの内容について、詳細な情報をお答えできませんでした。"

    if len(result) < 10 or "..." in result:
        result = "申し訳ございません。お尋ねの内容について、より詳しい情報をご提供するため、直接お問い合わせいただければと思います。"

    return result

def get_app_globals():
    """アプリのグローバル変数を取得"""
    try:
        import main
        return {
            'vectorstore': getattr(main, 'vectorstore', None),
            'rag_chain_template': getattr(main, 'rag_chain_template', None),
            'llm_instance': getattr(main, 'llm_instance', None)
        }
    except ImportError:
        logger.warning("Main module not available")
        return {}

tracer = RAGTracer()

# ============================================================================
# メインチャットエンドポイント（最適化版）
# ============================================================================
@router.post("/", summary="AI チャット（高速化・文章完全性強化版）")
async def chat_endpoint(req: ChatRequest, request: Request):
    """チャットエンドポイント（高速化・文章完全性強化版）"""
    logger.info(f"=== chat_endpoint called === question: {req.question}, username: {req.username}")

    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_time = time.time()

    answer = ""
    enhanced_info: dict = {}
    docs = []
    source = "unknown"

    try:
        # 1) 高速キャッシュチェック
        cached_answer = get_cached_response(query)
        if cached_answer:
            processing_time = time.time() - start_time
            logger.info(f"⚡ Cache response: {processing_time:.3f}s")
            
            # キャッシュ応答も完全性チェック
            complete_answer = ensure_complete_response(cached_answer, query)
            
            return {
                "answer": complete_answer,
                "sources": [],
                "status": "ok",
                "performance": {
                    "processing_time": processing_time,
                    "source": "cache",
                    "cache_hit": True
                }
            }

        # 2) テンプレート応答チェック（最高速）
        template_answer = get_template_response(query)
        if template_answer:
            processing_time = time.time() - start_time
            logger.info(f"🎯 Template response: {processing_time:.3f}s")
            
            # テンプレート応答も完全性チェック
            complete_template = ensure_complete_response(template_answer, query)
            cache_response(query, complete_template, "template")
            
            return {
                "answer": complete_template,
                "sources": [],
                "status": "ok",
                "performance": {
                    "processing_time": processing_time,
                    "source": "template",
                    "cache_hit": False
                }
            }

        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']

        logger.info(
            f"System status - Vectorstore: {vectorstore is not None}, "
            f"RAG chain: {rag_chain_template is not None}, LLM: {llm_instance is not None}"
        )

        # システム初期化チェック
        if not vectorstore and not llm_instance:
            logger.error("System not properly initialized")
            return JSONResponse(
                status_code=503,
                content={
                    "answer": "システムが正しく初期化されていません。管理者にお問い合わせください。",
                    "sources": [],
                    "status": "error",
                    "error": "Service temporarily unavailable"
                }
            )

        # 3) 雑談/挨拶は最短経路でLLMに
        if is_general_greeting_or_chat(query):
            logger.info("Detected general chat/greeting - using direct LLM response")
            answer = (
                get_general_response_from_llm(query, llm_instance)
                if llm_instance else
                ("こんにちは！ご質問をお聞かせください。" if "こんにちは" in query else "申し訳ございません。お手伝いできることがあれば、お気軽にお尋ねください。")
            )
            source = "llm_direct"

        # 4) RAG経路
        elif vectorstore and rag_chain_template:
            logger.info("Using RAG chain for technical/document-based query")
            try:
                # 検索 + トレース
                docs = vectorstore.similarity_search(query, k=3)
                tracer.trace_retrieval(query, docs)

                # 生成
                if hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": query})
                elif hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": query})
                else:
                    result = rag_chain_template({"query": query}, callbacks=[])

                raw_answer = result.get("result", "")
                logger.info(f"Raw RAG response: {raw_answer[:200]}...")

                # RAG応答のクリーンアップ
                cleaned_answer = clean_rag_response(raw_answer)
                
                # ハルチネーション対策の強化（外部統合）
                if ANTI_HALLUCINATION_AVAILABLE:
                    try:
                        enhanced_result = await enhance_web_chat_response(
                            query=query,
                            original_response=cleaned_answer,
                            user_context={"username": user}
                        )
                        answer = enhanced_result.get("answer") or cleaned_answer
                        enhanced_info = enhanced_result or {}
                    except Exception as e:
                        logger.error(f"Anti-hallucination processing failed: {e}")
                        answer = cleaned_answer
                else:
                    answer = cleaned_answer
                
                source = "rag"

                # 生成のトレース
                context = "\n".join([getattr(doc, "page_content", "") for doc in docs])
                tracer.trace_generation(query, context, answer)

                logger.info(
                    f"Enhanced response: {answer[:200]}... "
                    f"(anti_hallucination_used={enhanced_info.get('anti_hallucination_used', False)})"
                )

            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                logger.error(traceback.format_exc())
                answer = (
                    get_general_response_from_llm(query, llm_instance)
                    if llm_instance else
                    generate_fallback_response(query)
                )
                source = "fallback"

        # 5) LLMのみ
        else:
            answer = (
                get_general_response_from_llm(query, llm_instance)
                if llm_instance else
                generate_fallback_response(query)
            )
            source = "llm_fallback"

    except Exception as e:
        error_id = str(uuid4())[:8]
        logger.error(f"Unexpected error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        answer = f"システムエラーが発生しました。管理者にお問い合わせください。（エラーID: {error_id}）"
        source = "error"

    # 最終整形（完全性チェック必須）
    final_answer = ensure_complete_response(answer, query)
    processing_time = time.time() - start_time

    # キャッシュに保存（エラー以外）
    if source != "error":
        cache_response(query, final_answer, source)

    # ログ保存
    log = {
        "id": str(uuid4()),
        "question": query,
        "username": user,
        "answer": final_answer,
        "timestamp": now,
        "sources": [],
        "enhanced_info": enhanced_info,
        "performance": {
            "processing_time": processing_time,
            "source": source
        }
    }
    history_logs.append(log)

    # レスポンス
    resp = {
        "answer": final_answer,
        "sources": enhanced_info.get("sources", []),
        "status": "ok",
        "performance": {
            "processing_time": processing_time,
            "source": source,
            "cache_hit": False
        }
    }

    # デバッグモード: 検証情報を同梱
    if os.getenv("DEBUG_MODE", "").lower() == "true":
        resp["verification"] = {
            "method": enhanced_info.get("verification_method"),
            "note": enhanced_info.get("verification_note"),
            "confidence": enhanced_info.get("confidence_level"),
            "last_updated": enhanced_info.get("last_updated"),
            "warnings": enhanced_info.get("warnings", [])
        }

    logger.info(f"Final response: {final_answer[:100]}... (time: {processing_time:.3f}s, source: {source})")
    return resp

@router.post("", include_in_schema=False)
async def chat_endpoint_slashless(req: ChatRequest, request: Request):
    return await chat_endpoint(req, request)

# ============================================================================
# 管理・監視エンドポイント
# ============================================================================
@router.get("/performance-stats", summary="パフォーマンス統計取得")
def get_performance_stats():
    """パフォーマンス統計情報"""
    total_requests = _cache_stats["hits"] + _cache_stats["misses"]
    hit_rate = _cache_stats["hits"] / total_requests if total_requests > 0 else 0
    
    return {
        "cache_performance": {
            "size": len(_response_cache),
            "max_size": MAX_CACHE_SIZE,
            "hit_rate": hit_rate,
            "hits": _cache_stats["hits"],
            "misses": _cache_stats["misses"],
            "total_requests": total_requests
        },
        "template_performance": {
            "available_templates": len(FAST_TEMPLATES),
            "template_types": list(FAST_TEMPLATES.keys())
        },
        "features": [
            "Fast Template Responses",
            "Intelligent Caching",
            "Sentence Completion Guard",
            "Anti-Hallucination Integration",
            "Performance Monitoring"
        ],
        "performance_targets": {
            "template_response": "< 0.1s",
            "cache_response": "< 0.05s", 
            "rag_response": "< 2.0s",
            "cache_hit_rate_target": "> 60%"
        }
    }

@router.post("/clear-cache", summary="キャッシュクリア")
def clear_cache():
    """レスポンスキャッシュをクリア"""
    global _response_cache, _cache_stats
    old_size = len(_response_cache)
    _response_cache.clear()
    _cache_stats = {"hits": 0, "misses": 0}
    
    return {
        "status": "cache_cleared",
        "previous_size": old_size,
        "current_size": 0,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/history", summary="チャット履歴取得")
def get_history():
    return {"logs": history_logs}

@router.get("/export/csv", summary="チャット履歴 CSV ダウンロード")
def export_csv():
    import csv
    import io
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "question", "username", "answer", "timestamp"])
    for log in history_logs:
        writer.writerow([
            log.get("id", ""),
            log.get("question", ""),
            log.get("username", ""),
            log.get("answer", ""),
            log.get("timestamp", ""),
        ])
    si.seek(0)
    return StreamingResponse(
        si,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=chat_history.csv"}
    )

@router.get("/export/json", summary="チャット履歴 JSON ダウンロード")
def export_json():
    return JSONResponse(
        content=history_logs,
        headers={"Content-Disposition": "attachment; filename=chat_history.json"}
    )