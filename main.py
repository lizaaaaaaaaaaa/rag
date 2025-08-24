# main.py - RAG機能有効化版（PDF + Google検索 + ChatGPT統合）- LINE Bot RAG統合修正版

import logging
import os
import asyncio
import time
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List
import concurrent.futures
from uuid import uuid4
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI アプリケーションインスタンス
app = FastAPI(
    title="RAG API - Full RAG Edition with PDF + Search + ChatGPT",
    description="AI Chat API with PDF-based RAG, Google Search Anti-Hallucination, and ChatGPT Integration",
    version="3.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数（RAG機能有効化）
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False
initialization_in_progress = False

# 起動時刻を記録
startup_time = time.time()

# RAG初期化を有効化
DISABLE_RAG_INIT = False  # RAG機能を有効化
FORCE_TEMPLATE_MODE = False  # テンプレートモード強制を無効化
ENABLE_PDF_RAG = True  # PDFベースRAGを有効化
ENABLE_GOOGLE_SEARCH = True  # Google検索を有効化
ENABLE_CHATGPT_FALLBACK = True  # ChatGPT フォールバックを有効化

# ==============================================================================
# RAGコンポーネント初期化関数
# ==============================================================================
async def initialize_rag_components():
    """RAGコンポーネントの初期化（PDF + ベクトルストア + LLM）"""
    global vectorstore, rag_chain_template, llm_instance, is_initialized
    
    if is_initialized:
        return
    
    async with initialization_lock:
        if is_initialized:
            return
            
        logger.info("🚀 Initializing RAG components (PDF + Vector Store + LLM)...")
        
        try:
            # 1. Cloud StorageからPDFを読み込んでベクトルストアを構築
            vectorstore = await load_pdf_vectorstore()
            
            # 2. LLMインスタンスの初期化
            llm_instance = load_llm_instance()
            
            # 3. RAGチェーンの構築
            rag_chain_template = create_rag_chain(vectorstore, llm_instance)
            
            is_initialized = True
            logger.info("✅ RAG components initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ RAG initialization failed: {e}")
            logger.error(traceback.format_exc())
            # 初期化に失敗してもサーバーは起動できるようにする
            is_initialized = False

async def load_pdf_vectorstore():
    """Cloud StorageからPDFを読み込んでベクトルストアを構築"""
    try:
        from google.cloud import storage
        from langchain_community.document_loaders import PyPDFLoader
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        from langchain_openai import OpenAIEmbeddings
        from langchain_community.vectorstores import FAISS
        import tempfile
        
        logger.info("📚 Loading PDFs from Cloud Storage...")
        
        # Cloud Storage クライアント
        client = storage.Client()
        bucket_name = os.getenv("GCS_BUCKET_NAME", "run-sources-rag-cloud-project-asia-northeast1")
        bucket = client.bucket(bucket_name)
        
        # PDFファイルを検索
        blobs = list(bucket.list_blobs(prefix="pdfs/"))  # pdfs/ フォルダ内のPDFを想定
        pdf_blobs = [blob for blob in blobs if blob.name.endswith('.pdf')]
        
        if not pdf_blobs:
            logger.warning("⚠️ No PDF files found in Cloud Storage")
            return None
        
        logger.info(f"📄 Found {len(pdf_blobs)} PDF files")
        
        # ドキュメントを収集
        all_documents = []
        
        for blob in pdf_blobs:
            try:
                # 一時ファイルにダウンロード
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
                    blob.download_to_filename(temp_file.name)
                    
                    # PDFローダーでテキスト抽出
                    loader = PyPDFLoader(temp_file.name)
                    documents = loader.load()
                    
                    # メタデータにファイル名を追加
                    for doc in documents:
                        doc.metadata["source_file"] = blob.name
                    
                    all_documents.extend(documents)
                    logger.info(f"✅ Loaded {len(documents)} pages from {blob.name}")
                    
                    # 一時ファイルを削除
                    os.unlink(temp_file.name)
                    
            except Exception as e:
                logger.error(f"❌ Failed to load PDF {blob.name}: {e}")
                continue
        
        if not all_documents:
            logger.warning("⚠️ No documents loaded from PDFs")
            return None
        
        # テキスト分割
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        
        texts = text_splitter.split_documents(all_documents)
        logger.info(f"📝 Split into {len(texts)} chunks")
        
        # 埋め込みとベクトルストア作成
        embeddings = OpenAIEmbeddings(
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )
        
        vectorstore = FAISS.from_documents(texts, embeddings)
        logger.info("🎯 Vector store created successfully")
        
        return vectorstore
        
    except Exception as e:
        logger.error(f"❌ Vector store creation failed: {e}")
        logger.error(traceback.format_exc())
        return None

def load_llm_instance():
    """LLMインスタンスの初期化"""
    try:
        from langchain_openai import ChatOpenAI
        
        llm = ChatOpenAI(
            model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            max_tokens=int(os.getenv("MAX_NEW_TOKENS", "256"))
        )
        
        logger.info("🤖 LLM instance created successfully")
        return llm
        
    except Exception as e:
        logger.error(f"❌ LLM initialization failed: {e}")
        return None

def create_rag_chain(vectorstore, llm):
    """RAGチェーンの構築"""
    try:
        from langchain.chains import RetrievalQA
        from langchain.prompts import PromptTemplate
        
        if not vectorstore or not llm:
            return None
        
        # カスタムプロンプトテンプレート
        prompt_template = """あなたは住宅・建築の専門アドバイザーです。以下の情報を基に、正確で分かりやすい回答をしてください。

コンテキスト情報:
{context}

質問: {question}

回答する際の注意点:
1. コンテキスト情報を基に正確に回答してください
2. 情報が不足している場合は「詳細は資料をご確認ください」と答えてください
3. 自然で分かりやすい日本語で回答してください
4. 300字以内で簡潔に回答してください

回答:"""
        
        PROMPT = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vectorstore.as_retriever(
                search_kwargs={"k": int(os.getenv("RAG_SEARCH_K", "3"))}
            ),
            chain_type_kwargs={"prompt": PROMPT},
            return_source_documents=True
        )
        
        logger.info("🔗 RAG chain created successfully")
        return chain
        
    except Exception as e:
        logger.error(f"❌ RAG chain creation failed: {e}")
        return None

# ==============================================================================
# Google検索統合クラス
# ==============================================================================
class GoogleSearchIntegration:
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        self.engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
        self.enabled = bool(self.api_key and self.engine_id and ENABLE_GOOGLE_SEARCH)
        
        if self.enabled:
            logger.info("✅ Google Search integration enabled")
        else:
            logger.warning("⚠️ Google Search integration disabled (missing credentials)")
    
    async def search_and_verify(self, query: str, rag_answer: str) -> Dict[str, Any]:
        """Google検索でRAG回答を検証・補強"""
        if not self.enabled:
            return {
                "verified_answer": rag_answer,
                "search_used": False,
                "confidence": 0.8
            }
        
        try:
            import requests
            
            # Google Custom Search API呼び出し
            search_url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": self.api_key,
                "cx": self.engine_id,
                "q": query,
                "num": 3
            }
            
            response = requests.get(search_url, params=params, timeout=5)
            response.raise_for_status()
            
            search_results = response.json()
            items = search_results.get("items", [])
            
            if not items:
                return {
                    "verified_answer": rag_answer,
                    "search_used": False,
                    "confidence": 0.7
                }
            
            # 検索結果から要約を作成
            search_context = "\n".join([
                f"- {item['title']}: {item['snippet']}"
                for item in items[:3]
            ])
            
            # LLMで検証・統合
            if llm_instance:
                verification_prompt = f"""以下の情報を比較検証して、最終回答を生成してください。

【元の回答】
{rag_answer}

【Web検索結果】
{search_context}

【指示】
1. 元の回答と検索結果を比較してください
2. 矛盾がある場合は最新情報を優先してください
3. 補強できる情報があれば追加してください
4. 自然で分かりやすい日本語で300字以内で回答してください

【最終回答】"""
                
                verified_response = llm_instance.invoke(verification_prompt)
                verified_answer = verified_response.content if hasattr(verified_response, 'content') else str(verified_response)
                
                return {
                    "verified_answer": verified_answer,
                    "search_used": True,
                    "confidence": 0.9,
                    "search_results_count": len(items)
                }
            
            return {
                "verified_answer": rag_answer,
                "search_used": True,
                "confidence": 0.8
            }
            
        except Exception as e:
            logger.error(f"❌ Google search verification failed: {e}")
            return {
                "verified_answer": rag_answer,
                "search_used": False,
                "confidence": 0.7,
                "error": str(e)
            }

# ==============================================================================
# プラットフォーム分離対応キャッシュシステム
# ==============================================================================
class PlatformSeparatedCache:
    def __init__(self, max_size: int = 1000):
        # プラットフォーム別キャッシュ
        self.web_cache: Dict[str, Dict] = {}
        self.line_cache: Dict[str, Dict] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.stats = {"web_hits": 0, "web_misses": 0, "line_hits": 0, "line_misses": 0}
   
    def _generate_key(self, query: str, platform: str) -> str:
        normalized = f"{platform}:{query.lower().strip()[:200]}"
        return hashlib.md5(normalized.encode()).hexdigest()
   
    def get(self, query: str, platform: str = "web") -> Optional[Dict]:
        key = self._generate_key(query, platform)
        cache = self.web_cache if platform == "web" else self.line_cache
        
        if key in cache:
            self.access_times[key] = time.time()
            self.stats[f"{platform}_hits"] += 1
            logger.info(f"⚡ {platform.upper()} Cache HIT for: {query[:30]}...")
            return cache[key]
        
        self.stats[f"{platform}_misses"] += 1
        return None
   
    def set(self, query: str, response: Dict, platform: str = "web"):
        if len(self.web_cache) + len(self.line_cache) >= self.max_size:
            self._evict_oldest()
       
        key = self._generate_key(query, platform)
        cache = self.web_cache if platform == "web" else self.line_cache
        
        cache[key] = {
            "answer": response.get("answer", ""),
            "timestamp": time.time(),
            "query_original": query[:100],
            "source": response.get("source", "unknown"),
            "platform": platform,
            "confidence": response.get("confidence", 0.8),
            "search_used": response.get("search_used", False)
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 {platform.upper()} Cache SET for: {query[:30]}...")
   
    def _evict_oldest(self):
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            # どちらのキャッシュにあるかチェック
            if oldest_key in self.web_cache:
                del self.web_cache[oldest_key]
            elif oldest_key in self.line_cache:
                del self.line_cache[oldest_key]
            del self.access_times[oldest_key]
   
    def get_stats(self) -> Dict:
        total_web = self.stats["web_hits"] + self.stats["web_misses"]
        total_line = self.stats["line_hits"] + self.stats["line_misses"]
        
        return {
            "web_cache_size": len(self.web_cache),
            "line_cache_size": len(self.line_cache),
            "total_size": len(self.web_cache) + len(self.line_cache),
            "max_size": self.max_size,
            "web_stats": {
                "hits": self.stats["web_hits"],
                "misses": self.stats["web_misses"],
                "hit_rate": self.stats["web_hits"] / total_web if total_web > 0 else 0
            },
            "line_stats": {
                "hits": self.stats["line_hits"],
                "misses": self.stats["line_misses"],
                "hit_rate": self.stats["line_hits"] / total_line if total_line > 0 else 0
            }
        }

# ==============================================================================
# プラットフォーム分離応答生成クラス（RAG統合版）
# ==============================================================================
class PlatformSeparatedResponseGenerator:
    def __init__(self):
        self.cache = PlatformSeparatedCache(max_size=500)
        self.google_search = GoogleSearchIntegration()
        self.web_templates = self._load_web_templates()
        self.line_templates = self._load_line_templates()
        self.performance_metrics = {
            "web_requests": 0, "line_requests": 0, 
            "template_hits": 0, "rag_hits": 0, "fallback_hits": 0,
            "search_verifications": 0, "chatgpt_calls": 0
        }
       
    def _load_web_templates(self) -> Dict[str, str]:
        """Web専用テンプレート（基本的な挨拶やメニュー表示用）"""
        return {
            "AI相談": """AI住まい相談へようこそ！

住まいづくりに関するご質問をお気軽にどうぞ！

よくあるご質問：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

            "資料請求": """資料請求を承ります。

以下の情報をお送りください：
1. お名前（フルネーム）
2. ご住所（〒郵便番号から）
3. お電話番号
4. ご希望資料の種類

お送りする資料：
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送りいたします。""",
        }
   
    def _load_line_templates(self) -> Dict[str, str]:
        """LINE専用テンプレート（基本的な挨拶やメニュー表示用）"""
        return {
            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば：**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

            "資料請求": """📋 資料請求を承ります

**必要情報をお送りください**
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号
4️⃣ ご希望資料の種類

**お送りする資料**
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送りいたします！"""
        }
   
    async def generate_platform_response(self, query: str, platform: str = "web", user: str = "unknown") -> Dict[str, Any]:
        """プラットフォーム分離応答生成（RAG統合版）"""
        start_time = time.time()
        self.performance_metrics[f"{platform}_requests"] += 1
        
        try:
            # 1. プラットフォーム別キャッシュチェック
            cached_response = self.cache.get(query, platform)
            if cached_response:
                return {
                    "answer": cached_response["answer"],
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "platform": platform,
                    "status": "ok",
                    "confidence": cached_response.get("confidence", 0.8),
                    "search_used": cached_response.get("search_used", False)
                }
            
            # 2. 基本的なメニュー表示用テンプレートマッチング（挨拶、メニューのみ）
            templates = self.web_templates if platform == "web" else self.line_templates
            template_response = self._match_simple_template(query, templates)
            
            if template_response:
                self.performance_metrics["template_hits"] += 1
                result = {
                    "answer": template_response,
                    "processing_time": time.time() - start_time,
                    "source": "template",
                    "platform": platform,
                    "status": "ok",
                    "confidence": 1.0,
                    "search_used": False
                }
                self.cache.set(query, result, platform)
                return result
            
            # 3. RAG検索（PDFベース）
            if vectorstore and rag_chain_template and is_initialized:
                try:
                    logger.info(f"🔍 RAG search for: {query[:50]}...")
                    
                    # RAGチェーンで検索・回答生成
                    rag_result = rag_chain_template.invoke({"query": query})
                    rag_answer = rag_result.get("result", "")
                    source_docs = rag_result.get("source_documents", [])
                    
                    if rag_answer and len(rag_answer.strip()) > 20:
                        self.performance_metrics["rag_hits"] += 1
                        
                        # 4. Google検索でハルシネーション対策
                        verification_result = await self.google_search.search_and_verify(query, rag_answer)
                        final_answer = verification_result["verified_answer"]
                        
                        if verification_result["search_used"]:
                            self.performance_metrics["search_verifications"] += 1
                        
                        result = {
                            "answer": final_answer,
                            "processing_time": time.time() - start_time,
                            "source": "rag_verified" if verification_result["search_used"] else "rag",
                            "platform": platform,
                            "status": "ok",
                            "confidence": verification_result["confidence"],
                            "search_used": verification_result["search_used"],
                            "source_docs_count": len(source_docs)
                        }
                        
                        self.cache.set(query, result, platform)
                        return result
                        
                except Exception as rag_error:
                    logger.error(f"❌ RAG processing error: {rag_error}")
            
            # 5. ChatGPT APIフォールバック
            if ENABLE_CHATGPT_FALLBACK and llm_instance:
                try:
                    logger.info(f"🤖 ChatGPT fallback for: {query[:50]}...")
                    
                    chatgpt_prompt = f"""あなたは住宅・建築の専門アドバイザーです。
以下の質問に対して、住宅に関する一般的な知識を基に回答してください。

質問: {query}

回答する際の注意点:
1. 住宅・建築に関連する内容で回答してください
2. 具体的な数値や価格は「詳細はお問い合わせください」と答えてください
3. 自然で分かりやすい日本語で回答してください
4. 250字以内で簡潔に回答してください

回答:"""
                    
                    chatgpt_response = llm_instance.invoke(chatgpt_prompt)
                    chatgpt_answer = chatgpt_response.content if hasattr(chatgpt_response, 'content') else str(chatgpt_response)
                    
                    self.performance_metrics["chatgpt_calls"] += 1
                    
                    result = {
                        "answer": chatgpt_answer,
                        "processing_time": time.time() - start_time,
                        "source": "chatgpt",
                        "platform": platform,
                        "status": "ok",
                        "confidence": 0.7,
                        "search_used": False
                    }
                    
                    self.cache.set(query, result, platform)
                    return result
                    
                except Exception as chatgpt_error:
                    logger.error(f"❌ ChatGPT fallback error: {chatgpt_error}")
            
            # 6. 最終フォールバック
            self.performance_metrics["fallback_hits"] += 1
            fallback_response = self._generate_platform_fallback(query, platform)
            result = {
                "answer": fallback_response,
                "processing_time": time.time() - start_time,
                "source": "fallback",
                "platform": platform,
                "status": "ok",
                "confidence": 0.5,
                "search_used": False
            }
            
            self.cache.set(query, result, platform)
            return result
            
        except Exception as e:
            logger.error(f"Platform response generation error: {e}")
            return {
                "answer": self._generate_platform_fallback(query, platform),
                "processing_time": time.time() - start_time,
                "source": "error",
                "platform": platform,
                "status": "error",
                "confidence": 0.3,
                "search_used": False
            }
   
    def _match_simple_template(self, query: str, templates: Dict[str, str]) -> Optional[str]:
        """シンプルなテンプレートマッチング（挨拶・メニューのみ）"""
        query_lower = query.lower()
        
        # 非常に限定的なキーワードのみテンプレート応答
        simple_keywords = {
            "AI相談": ["ai相談を開始します", "ai住まい相談を開始します", "相談を開始"],
            "資料請求": ["資料請求をお願いします", "パンフレット請求をお願いします", "カタログ請求をお願いします"],
        }
        
        for template_key, keywords in simple_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                logger.info(f"🎯 Simple template match: {template_key}")
                return templates.get(template_key)
        
        return None
   
    def _generate_platform_fallback(self, query: str, platform: str) -> str:
        """プラットフォーム別フォールバック（RAG無効時）"""
        if platform == "line":
            return """ご質問ありがとうございます✨

申し訳ございませんが、一時的にシステムの準備中です。
詳しくはスタッフまでお問い合わせください。

📞 営業時間：9:00-18:00（水曜定休）"""
        else:  # web
            return """ご質問ありがとうございます。

申し訳ございませんが、一時的にシステムの準備中です。
詳しくはスタッフまでお問い合わせください。

営業時間：9:00-18:00（水曜定休日）"""

# ==============================================================================
# リクエストモデル
# ==============================================================================
class ChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"  # プラットフォーム指定

# グローバルインスタンス
platform_generator = PlatformSeparatedResponseGenerator()

# ==============================================================================
# 遅延読み込み関数（LINEルーター用）
# ==============================================================================
def ensure_vectorstore_loaded():
    """ベクトルストアの遅延読み込み"""
    global vectorstore
    return vectorstore

def ensure_rag_chain_loaded():
    """RAGチェーンの遅延読み込み"""
    global rag_chain_template
    return rag_chain_template

def ensure_llm_loaded():
    """LLMインスタンスの遅延読み込み"""
    global llm_instance
    return llm_instance

# ==============================================================================
# メインチャットエンドポイント（RAG統合版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def rag_integrated_chat_endpoint(req: ChatRequest, request: Request):
    """RAG統合チャットエンドポイント（PDF + Google検索 + ChatGPT）"""
    
    overall_start = time.time()
    platform = getattr(req, 'platform', 'web') or 'web'
    logger.info(f"🌐 RAG Chat ({platform}): {req.question[:50]}...")
    
    try:
        # RAG初期化確認
        if not is_initialized and not DISABLE_RAG_INIT:
            logger.info("🔄 Initializing RAG on first request...")
            await initialize_rag_components()
        
        # プラットフォーム分離RAG応答生成
        response = await platform_generator.generate_platform_response(
            req.question,
            platform=platform,
            user=req.username or f"{platform}-user"
        )
        
        total_time = time.time() - overall_start
        
        logger.info(f"✅ RAG Response ({platform}): {total_time:.3f}s, "
                   f"source={response.get('source')}, "
                   f"confidence={response.get('confidence', 0):.2f}, "
                   f"search_used={response.get('search_used', False)}")
        
        return {
            "answer": response["answer"],
            "sources": [],  # プライバシー保護のため非表示
            "status": response["status"],
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0),
                "source": response.get("source"),
                "platform": platform,
                "rag_enabled": True,
                "confidence": response.get("confidence", 0.8),
                "search_used": response.get("search_used", False),
                "source_docs_count": response.get("source_docs_count", 0)
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ RAG Chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        
        fallback_answer = platform_generator._generate_platform_fallback(
            req.question if hasattr(req, 'question') else "", platform
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": fallback_answer,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "platform": platform,
                    "rag_enabled": True,
                    "confidence": 0.3
                }
            }
        )

# ==============================================================================
# ヘルスチェック・システム状態
# ==============================================================================
@app.get("/healthz")
async def health_check():
    """ヘルスチェック"""
    uptime = time.time() - startup_time
    
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "message": "RAG API with PDF + Search + ChatGPT",
        "rag_initialized": is_initialized,
        "rag_disabled": DISABLE_RAG_INIT,
        "pdf_rag_enabled": ENABLE_PDF_RAG,
        "google_search_enabled": ENABLE_GOOGLE_SEARCH,
        "chatgpt_fallback_enabled": ENABLE_CHATGPT_FALLBACK,
        "vectorstore_ready": vectorstore is not None,
        "llm_ready": llm_instance is not None
    }

@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {
        "message": "RAG API - Full RAG Edition",
        "version": "3.0.0",
        "timestamp": datetime.now().isoformat(),
        "features": [
            "PDF-based RAG from Cloud Storage",
            "Google Search Anti-Hallucination",
            "ChatGPT API Integration",
            "Platform Separated Responses",
            "Smart Caching System",
            "LINE Bot RAG Integration"
        ],
        "rag_status": "enabled" if not DISABLE_RAG_INIT else "disabled",
        "uptime": time.time() - startup_time,
        "initialization_status": {
            "initialized": is_initialized,
            "vectorstore": vectorstore is not None,
            "llm": llm_instance is not None,
            "rag_chain": rag_chain_template is not None
        }
    }

@app.get("/system-status")
async def get_system_status():
    """システム状態取得"""
    cache_stats = platform_generator.cache.get_stats()
    perf_metrics = platform_generator.performance_metrics
    
    return {
        "rag_components": {
            "initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None,
            "rag_chain_ready": rag_chain_template is not None,
            "google_search_ready": platform_generator.google_search.enabled
        },
        "performance_metrics": perf_metrics,
        "cache_stats": cache_stats,
        "uptime": time.time() - startup_time,
        "rag_settings": {
            "disable_rag_init": DISABLE_RAG_INIT,
            "force_template_mode": FORCE_TEMPLATE_MODE,
            "enable_pdf_rag": ENABLE_PDF_RAG,
            "enable_google_search": ENABLE_GOOGLE_SEARCH,
            "enable_chatgpt_fallback": ENABLE_CHATGPT_FALLBACK
        },
        "version": "3.0.0",
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# LINE デバッグエンドポイント
# ==============================================================================
@app.get("/line-debug")
async def line_debug_status():
    """LINEボットのデバッグ情報"""
    return {
        "line_bot_status": "RAG Integrated",
        "router_used": "line_bot_fixed.py",
        "rag_integration": {
            "enabled": True,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None,
            "rag_chain_ready": rag_chain_template is not None
        },
        "timestamp": datetime.now().isoformat(),
        "message": "LINE Bot is now using RAG for intelligent responses"
    }

# ==============================================================================
# アプリケーション起動時の処理
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の処理"""
    logger.info("🚀 Starting RAG API with PDF + Search + ChatGPT...")
    
    # RAG初期化（バックグラウンドで実行）
    if not DISABLE_RAG_INIT:
        asyncio.create_task(initialize_rag_components())
    else:
        logger.warning("⚠️ RAG initialization disabled (DISABLE_RAG_INIT=True)")
    
    # LINE専用ルーター（RAG統合版に変更）
    try:
        from api.routers.line_bot_fixed import router as line_fixed_router
        app.include_router(line_fixed_router, prefix="/line", tags=["line-rag-integrated"])
        logger.info("✅ LINE RAG Integrated router added")
    except Exception as e:
        logger.error(f"❌ Failed to add LINE RAG router: {e}")
        # フォールバックとして ultra fast を使用
        try:
            from api.routers.line_bot_ultra_fast import router as ultra_line_router
            app.include_router(ultra_line_router, prefix="/line", tags=["line-ultra-fast"])
            logger.warning("⚠️ Fallback to LINE Ultra Fast router")
        except Exception as e2:
            logger.error(f"❌ Failed to add fallback LINE router: {e2}")
    
    # その他のルーター
    try:
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.warning(f"⚠️ Upload router not added: {e}")
    
    logger.info("🎉 RAG API startup completed with LINE RAG integration")
    logger.info(f"⚡ Startup time: {time.time() - startup_time:.2f} seconds")

@app.post("/clear-cache")
def clear_all_caches():
    """キャッシュクリア"""
    old_stats = platform_generator.cache.get_stats()
    platform_generator.cache = PlatformSeparatedCache(max_size=500)
    
    return {
        "status": "caches_cleared",
        "previous_stats": old_stats,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/reload-rag")
async def reload_rag_components():
    """RAGコンポーネントの再読み込み"""
    global is_initialized
    is_initialized = False
    await initialize_rag_components()
    
    return {
        "status": "rag_reloaded",
        "initialized": is_initialized,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)