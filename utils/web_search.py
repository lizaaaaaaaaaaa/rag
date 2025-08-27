# utils/web_search.py - 修正版（リッチメニュー押下時は無効化、AI相談時のみ有効）

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
        
        # リッチメニューの固定応答キーワード（Web検索を無効化）
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
            "チャット相談"
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
        short_keywords = ["AI相談", "資料請求", "展示場来場", "資金計画", "チャット相談"]
        for keyword in short_keywords:
            if query_stripped == keyword or query_stripped.endswith(keyword):
                logger.info(f"リッチメニュー関連キーワードを検出: {query}")
                return True
        
        return False
    
    def search_web(self, query: str, num_results: int = 5) -> List[Dict]:
        """Google Custom Search APIを使用してWeb検索"""
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
                "num": num_results,
                "hl": "ja",  # 日本語優先
                "gl": "jp",  # 日本の検索結果優先
            }
            
            response = requests.get(self.search_endpoint, params=params)
            response.raise_for_status()
            
            search_results = []
            data = response.json()
            
            if "items" in data:
                for item in data["items"][:num_results]:
                    search_results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                        "domain": item.get("displayLink", "")
                    })
            
            logger.info(f"Found {len(search_results)} search results for query: {query}")
            return search_results
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error("Google Search API quota exceeded")
            else:
                logger.error(f"Google Search API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []
    
    def get_enhanced_answer(self, query: str, context: str = "", use_web_search: bool = True) -> str:
        """Web検索結果も含めて強化された回答を生成（リッチメニュー押下時は固定応答優先）"""
        
        # リッチメニュー押下の場合は、Web検索を実行せず固定応答を優先
        if self.is_richmenu_action(query):
            logger.info(f"リッチメニュー押下のため固定テンプレート応答を優先: {query}")
            # 固定テンプレートシステムに任せるため、何も処理しない
            return ""
        
        # 坪単価の質問に特化した処理（AI相談での実際の質問時のみ）
        if "坪単価" in query and not self.is_richmenu_action(query):
            # コンテキストから坪単価情報を探す
            if context:
                # コンテキストに坪単価の情報があるか確認
                if "坪単価" in context or "万円/坪" in context or "価格" in context:
                    # OpenAI APIで回答生成
                    if self.openai_api_key:
                        try:
                            client = openai.OpenAI(api_key=self.openai_api_key)
                            response = client.chat.completions.create(
                                model="gpt-3.5-turbo",
                                messages=[
                                    {"role": "system", "content": "あなたは住宅の専門アドバイザーです。質問に対して親しみやすく、自然な日本語で回答してください。出典や参考文献については言及しないでください。"},
                                    {"role": "user", "content": f"以下の情報から坪単価について教えてください。\n\n情報: {context}\n\n自然で分かりやすい回答をお願いします。"}
                                ],
                                temperature=0.3,
                                max_tokens=300
                            )
                            return response.choices[0].message.content
                        except Exception as e:
                            logger.error(f"Error generating answer: {e}")
                
                # コンテキストに情報がない場合
                return "申し訳ございません。坪単価については、お客様のご希望や仕様によって異なるため、詳細なお見積りをご提供させていただきます。お気軽にお問い合わせください。"
        
        # Web検索結果を取得（AI相談での実際の質問時のみ）
        web_context = ""
        if use_web_search and self.should_search_web(query):
            logger.info(f"Performing web search for: {query}")
            search_results = self.search_web(query)
            
            if search_results:
                # Web検索情報を要約して含める
                web_snippets = []
                for result in search_results[:3]:  # 上位3件のみ使用
                    if result['snippet']:
                        web_snippets.append(result['snippet'])
                
                if web_snippets:
                    web_context = " ".join(web_snippets)
        
        # プロンプトを構築（自然な回答生成用）
        system_prompt = """あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
ユーザーの質問に対して、自然で分かりやすい回答を提供してください。

【重要な指示】
- 自然で親しみやすい日本語で回答する
- 出典や参考文献については一切言及しない
- デバッグ情報や検索結果の詳細は含めない
- 具体的で実用的な回答を心がける
- 専門用語は分かりやすく説明する"""

        # コンテキスト部分を構築
        context_parts = []
        if context and len(context.strip()) > 10:
            context_parts.append(f"参考情報: {context}")
        if web_context and len(web_context.strip()) > 10:
            context_parts.append(f"最新情報: {web_context}")
        
        context_section = "\n\n".join(context_parts) if context_parts else ""
        
        user_prompt = f"""質問: {query}

{context_section}

上記の情報を参考に、質問に対して自然で分かりやすい回答をお願いします。
専門的な内容も含めて、お客様にとって有用な情報を提供してください。"""

        try:
            if self.openai_api_key:
                client = openai.OpenAI(api_key=self.openai_api_key)
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=600
                )
                
                generated_answer = response.choices[0].message.content
                
                # 生成された回答をクリーンアップ
                return self._clean_generated_answer(generated_answer)
            else:
                return "申し訳ございません。回答を生成できませんでした。"
                
        except Exception as e:
            logger.error(f"Error generating enhanced answer: {e}")
            return "申し訳ございません。エラーが発生しました。もう一度お試しください。"
    
    def _clean_generated_answer(self, answer: str) -> str:
        """生成された回答をクリーンアップ"""
        import re
        
        # 不要なパターンを削除
        unwanted_patterns = [
            r"参考文献[:：][^\n]*",
            r"出典[:：][^\n]*",
            r"【[^】]*】",
            r"参考情報[:：]",
            r"最新情報[:：]",
            r"^情報[:：]\s*",
        ]
        
        cleaned = answer
        for pattern in unwanted_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE)
        
        # 余分な改行や空白を整理
        cleaned = re.sub(r'\n\s*\n', '\n', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        
        return cleaned
    
    def should_search_web(self, query: str) -> bool:
        """Web検索が必要かどうかを判定（リッチメニュー押下時は無効化）"""
        
        # リッチメニューの押下アクションの場合は絶対に検索しない
        if self.is_richmenu_action(query):
            logger.info(f"リッチメニュー押下のためWeb検索を無効化: {query}")
            return False
        
        # リッチメニュー関連の固定応答キーワードも検索対象外
        richmenu_related_keywords = [
            "展示場", "来場", "予約", "資料請求", "チャット相談", 
            "AI相談", "住まいサイト", "資金計画"
        ]
        
        query_lower = query.lower()
        for keyword in richmenu_related_keywords:
            if keyword.lower() in query_lower and len(query.strip()) < 20:  # 短いクエリの場合
                logger.info(f"リッチメニュー関連キーワード検出のためWeb検索をスキップ: {query}")
                return False
        
        # 最新情報が必要そうなキーワード（AI相談での実際の質問時のみ有効）
        current_keywords = [
            "最新", "現在", "今", "2024", "2025", "ニュース", 
            "天気", "株価", "為替", "最近", "新しい", "トレンド",
            "価格", "値段", "料金", "コスト"
        ]
        
        # 一般的な知識で答えられそうな質問
        general_keywords = [
            "とは", "って何", "意味", "定義", "歴史", "基本",
            "仕組み", "原理", "理論"
        ]
        
        # 技術的な質問でもバージョン情報が必要な場合
        tech_keywords = [
            "バージョン", "アップデート", "リリース", "最新版"
        ]
        
        # 最新情報が必要な場合（AI相談での実際の質問時のみ）
        if any(keyword in query for keyword in current_keywords):
            logger.info(f"最新情報が必要な質問のためWeb検索を実行: {query}")
            return True
        
        # 技術的な最新情報が必要な場合
        if any(keyword in query for keyword in tech_keywords):
            logger.info(f"技術的最新情報が必要な質問のためWeb検索を実行: {query}")
            return True
            
        # 一般的な質問の場合はFalse
        if any(keyword in query for keyword in general_keywords) and \
           not any(keyword in query for keyword in current_keywords):
            return False
            
        # 疑問詞で始まる具体的な質問は検索する可能性（但しリッチメニュー関連は除外済み）
        specific_questions = ["どこで", "いくら", "何円", "どの"]
        if any(query.startswith(q) for q in specific_questions):
            logger.info(f"具体的な質問のためWeb検索を実行: {query}")
            return True
            
        # デフォルトはFalse（RAGデータベースを優先）
        logger.info(f"RAGデータベース優先のためWeb検索をスキップ: {query}")
        return False

# グローバル検索インスタンス
_global_searcher = None

def get_google_searcher():
    """グローバル検索インスタンスを取得"""
    global _global_searcher
    if _global_searcher is None:
        _global_searcher = GoogleSearcher()
    return _global_searcher

def should_use_web_search(query: str) -> bool:
    """Web検索を使用すべきかの判定（外部からの呼び出し用）"""
    searcher = get_google_searcher()
    return searcher.should_search_web(query)

def is_richmenu_pressed(query: str) -> bool:
    """リッチメニューが押下されたかの判定（外部からの呼び出し用）"""
    searcher = get_google_searcher()
    return searcher.is_richmenu_action(query)

def perform_web_search_if_needed(query: str, context: str = "") -> str:
    """必要に応じてWeb検索を実行（リッチメニュー押下時は無効化）"""
    searcher = get_google_searcher()
    
    # リッチメニュー押下の場合は何もせず空文字列を返す（固定テンプレートに任せる）
    if searcher.is_richmenu_action(query):
        logger.info(f"リッチメニュー押下のためWeb検索をスキップし、固定テンプレートに委譲: {query}")
        return ""
    
    # AI相談での実際の質問の場合のみ実行
    if searcher.should_search_web(query):
        logger.info(f"AI相談での質問に対してWeb検索を実行: {query}")
        return searcher.get_enhanced_answer(query, context, use_web_search=True)
    else:
        logger.info(f"Web検索不要と判定、RAGデータベースに委譲: {query}")
        return ""