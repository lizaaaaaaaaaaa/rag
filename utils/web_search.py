# utils/web_search.py - 完全修正版（高速化・RAG優先・リッチメニュー対応）

import os
import logging
import requests
from typing import Dict, List, Optional
import openai
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

class GoogleSearcher:
    def __init__(self):
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        
        # Google Custom Search APIの設定
        self.google_api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
        self.google_cx = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")
        self.search_endpoint = "https://www.googleapis.com/customsearch/v1"
        
        # Web検索の有効化フラグ（デフォルトは無効）
        self.enable_web_search = os.environ.get("ENABLE_WEB_SEARCH", "false").lower() == "true"
        
        # リッチメニューの固定応答キーワード（Web検索を完全無効化）
        self.richmenu_keywords = [
            "🤖 AI相談",
            "🌐 AI住まいサイト", 
            "📋 資料請求",
            "📍 展示場来場",
            "💰 資金計画",
            "💬 チャット相談",
            "AI相談",
            "AI住まいサイト",
            "資料請求",
            "展示場来場",
            "資金計画",
            "チャット相談",
            "展示場来場　予約"
        ]
        
        # Secret Managerから取得する場合
        if not self.google_api_key and os.environ.get("ENV") == "production":
            self._load_from_secret_manager()
    
    def _load_from_secret_manager(self):
        """Google Secret Managerから認証情報を取得"""
        try:
            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
            
            # API Keyを取得
            api_key_name = f"projects/{project_id}/secrets/GOOGLE_SEARCH_API_KEY/versions/latest"
            api_key_response = client.access_secret_version(request={"name": api_key_name})
            self.google_api_key = api_key_response.payload.data.decode("UTF-8")
            
            # Search Engine IDを取得
            cx_name = f"projects/{project_id}/secrets/GOOGLE_SEARCH_ENGINE_ID/versions/latest"
            cx_response = client.access_secret_version(request={"name": cx_name})
            self.google_cx = cx_response.payload.data.decode("UTF-8")
            
        except Exception as e:
            logger.error(f"Failed to load secrets: {e}")
    
    def is_richmenu_action(self, query: str) -> bool:
        """リッチメニューの押下アクションかどうかを判定"""
        query_stripped = query.strip()
        
        # 完全一致チェック（絵文字付き・絵文字なし両方）
        for keyword in self.richmenu_keywords:
            if query_stripped == keyword:
                logger.info(f"リッチメニュー押下を検出: {query}")
                return True
        
        # 部分一致チェック（短いキーワードの場合）
        short_keywords = ["AI相談", "資料請求", "展示場来場", "資金計画", "チャット相談", "展示場来場　予約"]
        for keyword in short_keywords:
            if query_stripped == keyword or query_stripped.endswith(keyword):
                logger.info(f"リッチメニュー関連キーワードを検出: {query}")
                return True
        
        return False
    
    def search_web(self, query: str, num_results: int = 3) -> List[Dict]:
        """Google Custom Search APIを使用してWeb検索（高速化のため結果数を削減）"""
        
        # Web検索が無効化されている場合
        if not self.enable_web_search:
            logger.debug(f"Web検索が無効化されています: {query}")
            return []
        
        # リッチメニュー押下の場合はWeb検索を実行しない
        if self.is_richmenu_action(query):
            logger.info(f"リッチメニュー押下のためWeb検索をスキップ: {query}")
            return []
        
        if not self.google_api_key or not self.google_cx:
            logger.warning("Google Search API credentials not found")
            return []
        
        try:
            params = {
                "key": self.google_api_key,
                "cx": self.google_cx,
                "q": query,
                "num": min(num_results, 3),  # 最大3件に制限（高速化）
                "hl": "ja",  # 日本語優先
                "gl": "jp",  # 日本の検索結果優先
            }
            
            response = requests.get(self.search_endpoint, params=params, timeout=3)  # タイムアウト設定
            response.raise_for_status()
            
            search_results = []
            data = response.json()
            
            if "items" in data:
                for item in data["items"][:min(num_results, 3)]:
                    search_results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                        "domain": item.get("displayLink", "")
                    })
            
            logger.info(f"Found {len(search_results)} search results for query: {query}")
            return search_results
            
        except requests.exceptions.Timeout:
            logger.warning("Web search timeout")
            return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error("Google Search API quota exceeded")
            else:
                logger.error(f"Google Search API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []
    
    def get_enhanced_answer(self, query: str, context: str = "", use_web_search: bool = False) -> str:
        """Web検索結果も含めて強化された回答を生成（デフォルトは無効）"""
        
        # リッチメニュー押下の場合は、Web検索を実行せず固定応答を優先
        if self.is_richmenu_action(query):
            logger.info(f"リッチメニュー押下のため固定テンプレート応答を優先: {query}")
            return ""
        
        # Web検索が明示的に無効化されている場合は早期リターン
        if not use_web_search or not self.enable_web_search:
            logger.debug(f"Web検索無効のためRAGに委譲: {query}")
            return ""
        
        # Web検索結果を取得（明示的に有効な場合のみ）
        web_context = ""
        if use_web_search and self.should_search_web(query):
            logger.info(f"Performing web search for: {query}")
            search_results = self.search_web(query, num_results=2)  # 結果を2件に制限
            
            if search_results:
                # Web検索情報を要約して含める（上位2件のみ）
                web_snippets = []
                for result in search_results[:2]:
                    if result['snippet']:
                        web_snippets.append(result['snippet'][:100])  # スニペットを短縮
                
                if web_snippets:
                    web_context = " ".join(web_snippets)
        
        # Web検索結果がない場合は早期リターン
        if not web_context:
            return ""
        
        # プロンプトを構築（高速化のため簡潔に）
        system_prompt = "住宅・建築の専門アドバイザーとして、簡潔で実用的な回答をしてください。"
        
        # コンテキストを制限
        context_limited = context[:300] if context else ""
        web_context_limited = web_context[:200] if web_context else ""
        
        user_prompt = f"""質問: {query}

参考情報: {context_limited}
最新情報: {web_context_limited}

簡潔に回答してください。"""

        try:
            if self.openai_api_key:
                client = openai.OpenAI(api_key=self.openai_api_key)
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.5,
                    max_tokens=300  # トークン数を削減
                )
                
                generated_answer = response.choices[0].message.content
                return self._clean_generated_answer(generated_answer)
            else:
                return ""
                
        except Exception as e:
            logger.error(f"Error generating enhanced answer: {e}")
            return ""
    
    def _clean_generated_answer(self, answer: str) -> str:
        """生成された回答をクリーンアップ（※出典削除はしない）"""
        # ここでは**出典/参考/引用の削除は行わない**（回答は上位層で最終整形）
        return (answer or "").strip()
    
    def should_search_web(self, query: str) -> bool:
        """Web検索が必要かどうかを判定（デフォルトはFalse）"""
        
        # Web検索が無効化されている場合
        if not self.enable_web_search:
            return False
        
        # リッチメニューの押下アクションの場合は絶対に検索しない
        if self.is_richmenu_action(query):
            logger.info(f"リッチメニュー押下のためWeb検索を無効化: {query}")
            return False
        
        # リッチメニュー関連の固定応答キーワードも検索対象外
        richmenu_related_keywords = [
            "展示場", "来場", "予約", "資料請求", "チャット相談", 
            "AI相談", "住まいサイト", "資金計画", "AI住まいサイト"
        ]
        
        query_lower = query.lower()
        for keyword in richmenu_related_keywords:
            if keyword.lower() in query_lower and len(query.strip()) < 20:
                logger.info(f"リッチメニュー関連キーワード検出のためWeb検索をスキップ: {query}")
                return False
        
        # 最新情報が明確に必要な場合のみ（限定的）
        current_keywords = [
            "最新", "現在", "今日", "2024年", "2025年", "ニュース"
        ]
        
        # 明確に最新情報が必要な場合のみTrue
        if any(keyword in query for keyword in current_keywords):
            logger.info(f"最新情報が必要な質問のためWeb検索を検討: {query}")
            return True
        
        # デフォルトはFalse（RAGデータベースを優先）
        logger.debug(f"RAGデータベース優先のためWeb検索をスキップ: {query}")
        return False

# グローバル検索インスタンス（シングルトン）
_global_searcher = None

def get_google_searcher():
    """グローバル検索インスタンスを取得"""
    global _global_searcher
    if _global_searcher is None:
        _global_searcher = GoogleSearcher()
    return _global_searcher

def should_use_web_search(query: str) -> bool:
    """Web検索を使用すべきかの判定（外部からの呼び出し用）"""
    # 環境変数で無効化されている場合は即座にFalse
    if os.environ.get("ENABLE_WEB_SEARCH", "false").lower() != "true":
        return False
    
    searcher = get_google_searcher()
    return searcher.should_search_web(query)

def is_richmenu_pressed(query: str) -> bool:
    """リッチメニューが押下されたかの判定（外部からの呼び出し用）"""
    searcher = get_google_searcher()
    return searcher.is_richmenu_action(query)

def perform_web_search_if_needed(query: str, context: str = "") -> str:
    """必要に応じてWeb検索を実行（デフォルトは無効）"""
    # 環境変数で無効化されている場合は即座に空文字列を返す
    if os.environ.get("ENABLE_WEB_SEARCH", "false").lower() != "true":
        logger.debug(f"Web検索が無効化されているためスキップ: {query}")
        return ""
    
    searcher = get_google_searcher()
    
    # リッチメニュー押下の場合は何もせず空文字列を返す
    if searcher.is_richmenu_action(query):
        logger.info(f"リッチメニュー押下のためWeb検索をスキップし、固定テンプレートに委譲: {query}")
        return ""
    
    # 明示的に最新情報が必要な場合のみ実行
    if searcher.should_search_web(query):
        logger.info(f"最新情報が必要な質問に対してWeb検索を実行: {query}")
        return searcher.get_enhanced_answer(query, context, use_web_search=True)
    else:
        logger.debug(f"Web検索不要と判定、RAGデータベースに委譲: {query}")
        return ""