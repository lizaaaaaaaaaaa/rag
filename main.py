# main.py - 完全修正版（ULTRA FAST対応 / 既存機能維持）
# - 既存: トークン正規化・包括監視・LINE/LLM/RAG 初期化・診断エンドポイント
# - 追加: ULTRA_FAST_MODE / RAG超高速チェーン / 新規エンドポイント / ログ拡張

import os
import sys
import traceback
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
import psutil
import asyncio
import hmac
import hashlib
import base64

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log', mode='a') if os.getenv("ENV") != "production" else logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# =========================
# 速度関連 環境変数（重要）
# =========================
FAST_MODE = os.getenv("FAST_MODE", "false").lower() == "true"

# ★ 追加：ULTRA FAST モードと短縮タイムアウト（既定値を高速向けに調整）
ULTRA_FAST_MODE = os.getenv("ULTRA_FAST_MODE", "true").lower() == "true"
RAG_TIMEOUT = int(os.getenv("RAG_TIMEOUT", "10"))
LINE_RESPONSE_TIMEOUT = int(os.getenv("LINE_RESPONSE_TIMEOUT", "3"))  # 3秒に短縮（既定10→3）
RAG_ULTRA_TIMEOUT = int(os.getenv("RAG_ULTRA_TIMEOUT", "4"))          # 4秒に短縮（ULTRA用）
ENABLE_RESPONSE_CACHE = os.getenv("ENABLE_RESPONSE_CACHE", "false").lower() == "true"

# 互換：FAST_MODE／ULTRA_FAST_MODE のON時は観測や外部送信を最小化
if FAST_MODE:
    logger.info("🚀 Fast Mode Enabled")
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["DISABLE_LANGSMITH"] = "true"

if ULTRA_FAST_MODE:
    logger.info("🚀 Ultra Fast Mode Enabled - Sub-30-second response target")
    # 追い高速化設定
    os.environ["LANGCHAIN_TRACING_V2"] = "false"         # 念のため再指定
    os.environ["DISABLE_LANGSMITH"] = "true"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"       # トークナイザ並列でのオーバーヘッド抑制
    os.environ["HF_DATASETS_CACHE"] = "/tmp/hf_cache"    # I/O高速な一時ディレクトリをキャッシュに

# 環境変数読み込み（ローカル時のみ）
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv(".env")
    logger.info(">>> Loaded .env for local development")
else:
    logger.info(">>> Running in production mode")

# ★★★ 重要：トークン正規化関数（main.pyでも使用） ★★★
def normalize_credential(value: Any) -> str:
    """認証情報を安全にstring型に変換"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8')
        except UnicodeDecodeError:
            logger.error("Failed to decode credential from bytes")
            return ""
    credential_str = str(value).strip()
    if credential_str.startswith('Bearer '):
        credential_str = credential_str[7:].strip()
    if credential_str.startswith("b'") and credential_str.endswith("'"):
        credential_str = credential_str[2:-1]
    return credential_str

# セキュリティ強化：重要な環境変数のマスキング
def mask_sensitive_data(value: str, show_chars: int = 10) -> str:
    if not value:
        return "未設定"
    return f"{value[:show_chars]}..." if len(value) > show_chars else "設定済み"

# 環境変数デバッグログ（セキュリティ配慮）
logger.info("==== Environment Variables Status ====")
logger.info("ENV: %s", os.environ.get("ENV"))

# 正規化処理を適用
raw_openai_key = os.environ.get("OPENAI_API_KEY", "")
raw_line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
raw_line_secret = os.environ.get("LINE_CHANNEL_SECRET", "")

normalized_openai_key = normalize_credential(raw_openai_key)
normalized_line_token = normalize_credential(raw_line_token)
normalized_line_secret = normalize_credential(raw_line_secret)

# 正規化後の情報をログ出力
logger.info("OPENAI_API_KEY: %s (normalized: %d chars)",
           mask_sensitive_data(raw_openai_key), len(normalized_openai_key))
logger.info("LINE_CHANNEL_ACCESS_TOKEN: %s (normalized: %d chars)",
           mask_sensitive_data(raw_line_token), len(normalized_line_token))
logger.info("LINE_CHANNEL_SECRET: %s (normalized: %d chars)",
           mask_sensitive_data(raw_line_secret), len(normalized_line_secret))

# ★ 追加：ULTRA FAST 関連ログ
logger.info("ULTRA_FAST_MODE: %s", ULTRA_FAST_MODE)
logger.info("LINE_RESPONSE_TIMEOUT: %s seconds", LINE_RESPONSE_TIMEOUT)
logger.info("RAG_ULTRA_TIMEOUT: %s seconds", RAG_ULTRA_TIMEOUT)
if ULTRA_FAST_MODE:
    logger.info("🎯 Target: Sub-30-second response for rich menu interactions")

# 正規化された認証情報を環境変数に再設定（他のモジュールで使用するため）
if normalized_openai_key:
    os.environ["OPENAI_API_KEY"] = normalized_openai_key
if normalized_line_token:
    os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = normalized_line_token
if normalized_line_secret:
    os.environ["LINE_CHANNEL_SECRET"] = normalized_line_secret

logger.info("LINE_LOGIN_CHANNEL_ID: %s", mask_sensitive_data(os.environ.get("LINE_LOGIN_CHANNEL_ID", "")))
logger.info("LINE_LOGIN_CHANNEL_SECRET: %s", mask_sensitive_data(os.environ.get("LINE_LOGIN_CHANNEL_SECRET", "")))
logger.info("LINE_LOGIN_REDIRECT_URI: %s", os.environ.get("LINE_LOGIN_REDIRECT_URI"))
logger.info("LIFF_ID: %s", os.environ.get("LIFF_ID"))
logger.info("GOOGLE_CLOUD_PROJECT: %s", os.environ.get("GOOGLE_CLOUD_PROJECT"))
logger.info("=====================================")

# LINE SDK availability check
try:
    from linebot.v3 import WebhookHandler
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 available")
except ImportError:
    LINE_SDK_AVAILABLE = False
    logger.warning("⚠️ LINE Bot SDK not available")

# FastAPI初期化（高度な設定）
app = FastAPI(
    title="RAG FastAPI Backend with Comprehensive Monitoring",
    description="RAG + LLM連携API (Cloud Run対応) + LINE Bot + 包括的監視システム",
    version="2.2.0",
    docs_url="/docs" if os.getenv("ENV") != "production" else None,
    redoc_url="/redoc" if os.getenv("ENV") != "production" else None
)

# セキュリティミドルウェア
if os.getenv("ENV") == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "rag-api-190389115361.asia-northeast1.run.app",
            "*.run.app",
            "localhost"
        ]
    )

# CORS設定（拡張版・LIFFサポート）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://leafy-kitsune-eb4566.netlify.app",
        "https://preview.studio.site",
        "https://*.studio.site",
        "https://liff.line.me",
        "https://liff-v2.line.me",
        f"https://liff.line.me/{os.environ.get('LIFF_ID', '2007887876-vMNe74eX')}",
        "https://rag-frontend-190389115361.asia-northeast1.run.app",
        "http://localhost:3000",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "*"  # 開発時のみ - 本番では削除推奨
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
)

# 高度なセキュリティヘッダー
@app.middleware("http")
async def add_comprehensive_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https: https://static.line-scdn.net https://d.line-scdn.net; "
        "style-src 'self' 'unsafe-inline' https:; "
        "connect-src 'self' https: wss: https://api.line.me https://access.line.me https://notify-api.line.me; "
        "img-src 'self' https: data:; "
        "font-src 'self' https: data:; "
        "frame-src https://liff.line.me https://liff-v2.line.me; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if os.getenv("ENV") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# パフォーマンス監視ミドルウェア
@app.middleware("http")
async def monitor_performance(request: Request, call_next):
    start_time = datetime.now()
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    user_agent = request.headers.get("User-Agent", "unknown")
    response = await call_next(request)
    process_time = (datetime.now() - start_time).total_seconds()
    if process_time > 5.0:
        logger.warning(f"Slow request: {request.method} {request.url.path} took {process_time:.2f}s")
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Timestamp"] = start_time.isoformat()
    return response

# ★★★ システム監視クラス ★★★
class SystemMonitor:
    def __init__(self):
        self.startup_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.health_checks = []
        self.last_health_check = None
        self.credential_normalizations = 0
    
    def record_request(self):
        self.request_count += 1
    
    def record_error(self):
        self.error_count += 1
    
    def record_credential_normalization(self):
        self.credential_normalizations += 1
    
    def get_system_metrics(self) -> Dict[str, Any]:
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            process = psutil.Process()
            process_memory = process.memory_info()
            return {
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "memory_total_gb": memory.total / (1024**3),
                    "memory_available_gb": memory.available / (1024**3),
                    "disk_percent": (disk.used / disk.total) * 100,
                    "disk_total_gb": disk.total / (1024**3),
                    "disk_free_gb": disk.free / (1024**3)
                },
                "process": {
                    "memory_rss_mb": process_memory.rss / (1024**2),
                    "memory_vms_mb": process_memory.vms / (1024**2),
                    "cpu_percent": process.cpu_percent(),
                    "threads": process.num_threads(),
                    "open_files": len(process.open_files())
                },
                "application": {
                    "uptime_seconds": (datetime.now() - self.startup_time).total_seconds(),
                    "request_count": self.request_count,
                    "error_count": self.error_count,
                    "error_rate": self.error_count / max(self.request_count, 1),
                    "credential_normalizations": self.credential_normalizations
                }
            }
        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            return {"error": str(e)}

# グローバル監視インスタンス
system_monitor = SystemMonitor()

# 正規化実行の記録
if normalized_openai_key or normalized_line_token or normalized_line_secret:
    system_monitor.record_credential_normalization()

# グローバル変数（メイン処理用）
vectorstore = None
rag_chain_template = None
llm_instance = None

# ★★★ 拡張スタートアップ処理 ★★★
@app.on_event("startup")
async def enhanced_startup():
    global startup_time, vectorstore, rag_chain_template, llm_instance
    startup_time = datetime.now()
    logger.info("🚀 Enhanced startup process initiated")
    logger.info("=" * 60)

    # 1. システムチェック
    try:
        logger.info("📊 System Resource Check:")
        cpu_count = psutil.cpu_count()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        logger.info(f"  CPU cores: {cpu_count}")
        logger.info(f"  Total memory: {memory.total / (1024**3):.2f} GB")
        logger.info(f"  Available memory: {memory.available / (1024**3):.2f} GB")
        logger.info(f"  Memory usage: {memory.percent:.1f}%")
        logger.info(f"  Disk usage: {(disk.used / disk.total) * 100:.1f}%")
        if memory.available < 1 * (1024**3):
            logger.warning("⚠️ Low memory warning: Less than 1GB available")
        if (disk.used / disk.total) > 0.9:
            logger.warning("⚠️ High disk usage warning: Over 90% used")
    except Exception as e:
        logger.error(f"❌ System resource check failed: {e}")

    # 2. Cloud Run環境情報
    try:
        logger.info("☁️ Cloud Run Environment:")
        cloud_run_info = {
            "service_name": os.environ.get("K_SERVICE", "local"),
            "revision": os.environ.get("K_REVISION", "local"),
            "configuration": os.environ.get("K_CONFIGURATION", "local"),
            "region": os.environ.get("GOOGLE_CLOUD_REGION", "unknown"),
            "project": os.environ.get("GOOGLE_CLOUD_PROJECT", "unknown")
        }
        for key, value in cloud_run_info.items():
            logger.info(f"  {key}: {value}")
    except Exception as e:
        logger.error(f"❌ Cloud Run info collection failed: {e}")

    # 3. LLM初期化（正規化された認証情報使用）
    try:
        logger.info("🧠 Loading LLM...")
        from llm.llm_runner import load_llm
        llm, tokenizer, max_tokens = load_llm()
        llm_instance = llm
        logger.info(f"✅ LLM loaded: {type(llm).__name__}")
        try:
            test_response = llm.invoke("こんにちは") if hasattr(llm, "invoke") else llm("こんにちは")
            logger.info("✅ LLM test successful")
        except Exception as e:
            logger.warning(f"⚠️ LLM test warning (non-critical): {e}")
    except Exception as e:
        logger.error(f"❌ LLM load failed: {e}")
        logger.error(traceback.format_exc())
        llm_instance = None

    # 4. ベクトルストア初期化
    try:
        logger.info("🔍 Loading Vectorstore...")
        from rag.ingested_text import load_vectorstore
        vectorstore = load_vectorstore()
        if vectorstore:
            logger.info("✅ Vectorstore loaded successfully")
            try:
                test_results = vectorstore.similarity_search("住宅", k=1)
                logger.info(f"✅ Vectorstore test successful: {len(test_results)} results")
            except Exception as e:
                logger.warning(f"⚠️ Vectorstore test warning: {e}")
        else:
            logger.warning("⚠️ Vectorstore is None")
    except Exception as e:
        logger.warning(f"⚠️ Vectorstore load failed: {e}")
        vectorstore = None

    # 5. RAGチェーン構築（超高速版対応）
    try:
        if vectorstore and llm_instance:
            logger.info("⛓️ Building ultra fast RAG chain...")
            if ULTRA_FAST_MODE:
                try:
                    # Ultra Fast 実装が存在する場合のみ使用（なければ従来へフォールバック）
                    from rag.fast_rag_chain import get_ultra_fast_rag_chain  # type: ignore
                    rag_chain_template = get_ultra_fast_rag_chain(vectorstore=vectorstore, return_source=True)
                    logger.info("✅ Ultra fast RAG chain created")
                except Exception as import_err:
                    logger.warning(f"⚠️ Ultra fast chain not available, fallback to standard: {import_err}")
                    from rag.ingested_text import get_rag_chain
                    rag_chain_template = get_rag_chain(vectorstore=vectorstore, return_source=True)
                    logger.info("✅ Standard RAG chain created (fallback)")
            else:
                from rag.ingested_text import get_rag_chain
                rag_chain_template = get_rag_chain(vectorstore=vectorstore, return_source=True)
                logger.info("✅ Standard RAG chain created")

            # テスト実行（応答時間の計測をログ）
            try:
                test_query = "テスト"
                start_time = datetime.now()
                test_result = rag_chain_template.invoke({"query": test_query})
                response_time = (datetime.now() - start_time).total_seconds()
                if test_result:
                    logger.info(f"✅ RAG chain test successful ({response_time:.2f}s)")
                else:
                    logger.warning("⚠️ RAG chain returned empty result")
            except Exception as e:
                logger.warning(f"⚠️ RAG chain test warning: {e}")

        elif vectorstore:
            logger.info("⛓️ Building search-only chain...")
            class SimpleSearchChain:
                def __init__(self, vectorstore):
                    self.vectorstore = vectorstore
                    self.retriever = vectorstore.as_retriever()
                    self.callbacks = []
                def invoke(self, inputs):
                    query = inputs.get("query", "")
                    docs = self.retriever.invoke(query)
                    if docs:
                        result = "関連情報:\n\n"
                        for i, doc in enumerate(docs[:3], 1):
                            content = doc.page_content[:300]
                            source = doc.metadata.get('source', '不明')
                            page = doc.metadata.get('page', '?')
                            result += f"{i}. {content}...\n出典: {source} (p{page})\n\n"
                    else:
                        result = "関連する文書が見つかりませんでした。"
                    return {"result": result, "source_documents": docs[:3]}
            rag_chain_template = SimpleSearchChain(vectorstore)
            logger.info("✅ Search-only chain created")
        else:
            logger.warning("⚠️ No vectorstore available for RAG chain")
            rag_chain_template = None
    except Exception as e:
        logger.error(f"❌ RAG chain creation failed: {e}")
        logger.error(traceback.format_exc())
        rag_chain_template = None

    # 6. LINE Bot設定確認（正規化後）
    try:
        logger.info("📱 LINE Bot Configuration Check:")
        line_checks = {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(normalized_line_token),
            "LINE_CHANNEL_SECRET": bool(normalized_line_secret),
            "LINE_LOGIN_CHANNEL_ID": bool(os.environ.get('LINE_LOGIN_CHANNEL_ID')),
            "LINE_LOGIN_CHANNEL_SECRET": bool(os.environ.get('LINE_LOGIN_CHANNEL_SECRET')),
            "LIFF_ID": bool(os.environ.get('LIFF_ID'))
        }
        for key, status in line_checks.items():
            logger.info(f"  {key}: {'✅ Set' if status else '❌ Not set'}")
        
        if normalized_line_token:
            logger.info(f"  Token normalized length: {len(normalized_line_token)}")
            logger.info(f"  Token format valid: {len(normalized_line_token) > 100}")
        if normalized_line_secret:
            logger.info(f"  Secret normalized length: {len(normalized_line_secret)}")
            logger.info(f"  Secret format valid: {len(normalized_line_secret) > 20}")
            
        if LINE_SDK_AVAILABLE:
            logger.info("  LINE SDK: ✅ Available (v3.5.0)")
        else:
            logger.warning("  LINE SDK: ⚠️ Not available")
    except Exception as e:
        logger.error(f"❌ LINE Bot configuration check failed: {e}")

    # 7. 起動完了サマリー
    startup_duration = (datetime.now() - startup_time).total_seconds()
    logger.info("=" * 60)
    logger.info("🎉 Enhanced Startup Complete!")
    logger.info(f"⏱️ Startup duration: {startup_duration:.2f} seconds")
    logger.info("=" * 60)
    components_status = {
        "LLM": "✅ Loaded" if llm_instance else "❌ Not loaded",
        "VectorStore": "✅ Loaded" if vectorstore else "❌ Not loaded",
        "RAG Chain": "✅ Created" if rag_chain_template else "❌ Not created",
        "LINE Bot": "✅ Configured" if normalized_line_token and normalized_line_secret else "❌ Not configured",
        "LINE Login": "✅ Configured" if os.environ.get('LINE_LOGIN_CHANNEL_ID') and os.environ.get('LINE_LOGIN_CHANNEL_SECRET') else "❌ Not configured",
        "LIFF": "✅ Configured" if os.environ.get('LIFF_ID') else "❌ Not configured"
    }
    logger.info("📊 Component Status:")
    for component, status in components_status.items():
        logger.info(f"  {component}: {status}")
    logger.info("=" * 60)
    logger.info(f"🌐 Service ready at: {datetime.now().isoformat()}")
    logger.info("=" * 60)

# ★★★ ルーター登録 ★★★
from api.routers import upload, chat, google_oauth, healthz, line_bot, line_login

# 基本ルーター
app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])

# /healthz は本ファイルで提供するため、詳細版は /ops 配下へ
app.include_router(healthz.router, prefix="/ops", tags=["healthz-ops"])

# LINE関連ルーター
app.include_router(line_bot.router, tags=["line"])
app.include_router(line_login.router, tags=["line-login"])

# 静的ファイル
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

# ★★★ 新しく追加するデバッグエンドポイント ★★★
@app.get("/line-debug")
def line_debug_endpoint():
    """LINE Bot設定のデバッグ情報（正規化対応）"""
    try:
        return {
            "line_credentials": {
                "access_token_set": bool(normalized_line_token),
                "channel_secret_set": bool(normalized_line_secret),
                "access_token_length": len(normalized_line_token) if normalized_line_token else 0,
                "secret_length": len(normalized_line_secret) if normalized_line_secret else 0,
                "access_token_preview": (normalized_line_token[:20] + "...") if normalized_line_token else "未設定",
                "secret_preview": (normalized_line_secret[:10] + "...") if normalized_line_secret else "未設定",
                "normalization_applied": {
                    "openai_key": bool(normalized_openai_key),
                    "line_token": bool(normalized_line_token),
                    "line_secret": bool(normalized_line_secret)
                }
            },
            "line_login_credentials": {
                "login_channel_id_set": bool(os.environ.get("LINE_LOGIN_CHANNEL_ID")),
                "login_channel_secret_set": bool(os.environ.get("LINE_LOGIN_CHANNEL_SECRET")),
                "liff_id_set": bool(os.environ.get("LIFF_ID")),
                "login_redirect_uri": os.environ.get("LINE_LOGIN_REDIRECT_URI", "未設定")
            },
            "webhook_info": {
                "webhook_url": "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
                "liff_url": f"https://liff.line.me/{os.environ.get('LIFF_ID', 'not-set')}",
                "expected_domain": "rag-api-190389115361.asia-northeast1.run.app"
            },
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "environment": os.environ.get("ENV", "unknown"),
            "cloud_run_info": {
                "service_name": os.environ.get("K_SERVICE", "local"),
                "revision": os.environ.get("K_REVISION", "local"),
                "region": os.environ.get("GOOGLE_CLOUD_REGION", "unknown")
            },
            "credential_normalization_count": system_monitor.credential_normalizations,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/test-line-signature")
def test_line_signature():
    """署名検証のテスト（正規化対応）"""
    try:
        if not normalized_line_secret:
            return {"error": "LINE_CHANNEL_SECRET not found or normalized"}
        test_body = '{"events":[],"destination":"test"}'
        hash = hmac.new(
            normalized_line_secret.encode('utf-8'),
            test_body.encode('utf-8'),
            hashlib.sha256
        ).digest()
        signature = base64.b64encode(hash).decode('utf-8')
        return {
            "test_body": test_body,
            "generated_signature": signature,
            "channel_secret_length": len(normalized_line_secret),
            "signature_format": f"X-Line-Signature: {signature}",
            "normalization_info": {
                "original_type": str(type(os.environ.get("LINE_CHANNEL_SECRET"))),
                "normalized_length": len(normalized_line_secret),
                "normalization_applied": normalized_line_secret != os.environ.get("LINE_CHANNEL_SECRET", "")
            },
            "verification_steps": [
                "1. Get body as bytes",
                "2. Get channel secret (normalized)",
                "3. HMAC-SHA256(secret, body)",
                "4. Base64 encode result",
                "5. Compare with X-Line-Signature header"
            ],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/line-webhook-test")
def line_webhook_test():
    """Webhook接続テスト"""
    try:
        import requests
        webhook_url = "https://rag-api-190389115361.asia-northeast1.run.app/line/status"
        try:
            response = requests.get(webhook_url, timeout=10)
            webhook_accessible = response.status_code == 200
            webhook_response = response.text if response.status_code == 200 else f"HTTP {response.status_code}"
        except requests.exceptions.RequestException as e:
            webhook_accessible = False
            webhook_response = str(e)
        return {
            "webhook_url": webhook_url,
            "webhook_accessible": webhook_accessible,
            "webhook_response": webhook_response,
            "line_developers_settings": {
                "webhook_url": "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
                "webhook_use": "Enable",
                "auto_reply": "Disable",
                "greeting_message": "Disable"
            },
            "dns_check": {
                "domain": "rag-api-190389115361.asia-northeast1.run.app",
                "expected_ip": "Cloud Run IP",
                "note": "Domain should resolve to Google Cloud Run"
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/line-credentials-validation")
def line_credentials_validation():
    """LINE認証情報の詳細検証（正規化対応）"""
    try:
        results = {
            "validation_results": {},
            "recommendations": [],
            "critical_issues": [],
            "normalization_info": {},
            "timestamp": datetime.now().isoformat()
        }
        results["normalization_info"] = {
            "openai_key_normalized": bool(normalized_openai_key),
            "line_token_normalized": bool(normalized_line_token),
            "line_secret_normalized": bool(normalized_line_secret),
            "normalization_count": system_monitor.credential_normalizations
        }
        if normalized_line_token:
            if len(normalized_line_token) < 100:
                results["critical_issues"].append("Access token seems too short after normalization")
            else:
                results["validation_results"]["access_token"] = "Format OK (normalized)"
        else:
            results["critical_issues"].append("LINE_CHANNEL_ACCESS_TOKEN not set or normalization failed")
        if normalized_line_secret:
            if len(normalized_line_secret) < 20:
                results["critical_issues"].append("Channel secret seems too short after normalization")
            else:
                results["validation_results"]["channel_secret"] = "Format OK (normalized)"
        else:
            results["critical_issues"].append("LINE_CHANNEL_SECRET not set or normalization failed")
        if normalized_line_token:
            try:
                import requests
                api_response = requests.get(
                    "https://api.line.me/v2/bot/info",
                    headers={"Authorization": f"Bearer {normalized_line_token}"},
                    timeout=10
                )
                if api_response.status_code == 200:
                    results["validation_results"]["api_connection"] = "Success (with normalized token)"
                    bot_info = api_response.json()
                    results["validation_results"]["bot_info"] = {
                        "displayName": bot_info.get("displayName", "Unknown"),
                        "userId": bot_info.get("userId", "Unknown"),
                        "basicId": bot_info.get("basicId", "Unknown")
                    }
                else:
                    results["critical_issues"].append(f"LINE API connection failed: HTTP {api_response.status_code}")
            except Exception as api_error:
                results["critical_issues"].append(f"LINE API connection error: {str(api_error)}")
        if not results["critical_issues"]:
            results["recommendations"].append("All LINE credentials are properly configured and normalized")
            results["recommendations"].append("Test webhook by sending a message to your LINE Bot")
        else:
            results["recommendations"].append("Fix critical issues before testing")
            results["recommendations"].append("Check Secret Manager configuration")
            results["recommendations"].append("Verify credential normalization process")
            results["recommendations"].append("Check LINE Developers Console settings")
        return results
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

# ★★★ LIFF アプリ対応 ★★★
@app.get("/liff")
async def serve_liff_app():
    liff_id = os.environ.get("LIFF_ID", "2007887876-vMNe74eX")
    try:
        liff_html_path = "liff_app.html"
        if os.path.exists(liff_html_path):
            with open(liff_html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            html_content = html_content.replace("YOUR_LIFF_ID", liff_id)
            html_content = html_content.replace("YOUR_API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
            return HTMLResponse(content=html_content)
        else:
            html_content = f"""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>キノエデザイン AI住まい相談</title>
    <script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 400px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }}
        .header {{ text-align: center; margin-bottom: 20px; }}
        .chat-area {{ min-height: 300px; border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin-bottom: 15px; }}
        .input-area {{ display: flex; gap: 10px; }}
        input {{ flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
        button {{ padding: 10px 20px; background: #06C755; color: white; border: none; border-radius: 5px; cursor: pointer; }}
        .message {{ margin-bottom: 10px; padding: 8px; border-radius: 8px; }}
        .user {{ background: #e1f5fe; margin-left: 20px; }}
        .ai {{ background: #f1f8e9; margin-right: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🏠 キノエデザイン</h2>
            <p>AI住まい相談</p>
        </div>
        <div id="chatArea" class="chat-area">
            <div class="message ai">こんにちは！住まいに関するご質問をお聞かせください🏠</div>
        </div>
        <div class="input-area">
            <input type="text" id="messageInput" placeholder="メッセージを入力..." />
            <button onclick="sendMessage()">送信</button>
        </div>
    </div>

    <script>
        async function initializeLiff() {{
            try {{
                await liff.init({{ liffId: '{liff_id}' }});
                console.log('LIFF initialized');
            }} catch (error) {{
                console.error('LIFF initialization failed', error);
            }}
        }}

        async function sendMessage() {{
            const input = document.getElementById('messageInput');
            const message = input.value.trim();
            if (!message) return;
            const chatArea = document.getElementById('chatArea');
            chatArea.innerHTML += `<div class="message user">${{message}}</div>`;
            input.value = '';
            try {{
                const response = await fetch('https://rag-api-190389115361.asia-northeast1.run.app/chat/', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ question: message, username: 'liff-user' }})
                }});
                const data = await response.json();
                chatArea.innerHTML += `<div class="message ai">${{data.answer || 'エラーが発生しました'}}</div>`;
            }} catch (error) {{
                chatArea.innerHTML += `<div class="message ai">エラーが発生しました。再度お試しください。</div>`;
            }}
            chatArea.scrollTop = chatArea.scrollHeight;
        }}
        document.getElementById('messageInput').addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') {{
                sendMessage();
            }}
        }});
        initializeLiff();
    </script>
</body>
</html>
            """
            return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"LIFF app error: {e}")
        return HTMLResponse(
            content=f"""
            <html>
                <body>
                    <h1>LIFF App Error</h1>
                    <p>エラーが発生しました: {e}</p>
                    <p>LIFF ID: {liff_id}</p>
                </body>
            </html>
            """,
            status_code=500
        )

# ★★★ システムヘルスチェック（包括版）★★★
@app.get("/system-health")
def comprehensive_system_health():
    try:
        metrics = system_monitor.get_system_metrics()
        components_status = {
            "llm": llm_instance is not None,
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None,
            "line_bot": bool(normalized_line_token and normalized_line_secret),
            "line_login": bool(os.environ.get("LINE_LOGIN_CHANNEL_ID") and os.environ.get("LINE_LOGIN_CHANNEL_SECRET")),
            "liff": bool(os.environ.get("LIFF_ID")),
            "credential_normalization": system_monitor.credential_normalizations > 0
        }
        cloud_run_info = {
            "service_name": os.environ.get("K_SERVICE", "local"),
            "revision": os.environ.get("K_REVISION", "local"),
            "configuration": os.environ.get("K_CONFIGURATION", "local"),
            "region": os.environ.get("GOOGLE_CLOUD_REGION", "unknown")
        }
        all_critical_healthy = all([
            components_status["llm"] or components_status["vectorstore"],
            metrics.get("system", {}).get("cpu_percent", 100) < 90,
            metrics.get("system", {}).get("memory_percent", 100) < 90
        ])
        health_status = "healthy" if all_critical_healthy else "degraded"
        if metrics.get("application", {}).get("error_rate", 0) > 0.1:
            health_status = "degraded"
        return {
            "status": health_status,
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": metrics.get("application", {}).get("uptime_seconds", 0),
            "cloud_run": cloud_run_info,
            "system_metrics": metrics,
            "components": components_status,
            # ★ 追加: ULTRA FAST の稼働状況
            "ultra_fast_mode": {
                "enabled": ULTRA_FAST_MODE,
                "line_timeout": LINE_RESPONSE_TIMEOUT,
                "rag_timeout": RAG_ULTRA_TIMEOUT,
                "target_response_time": "sub_30_seconds"
            },
            "health_indicators": {
                "cpu_healthy": metrics.get("system", {}).get("cpu_percent", 100) < 80,
                "memory_healthy": metrics.get("system", {}).get("memory_percent", 100) < 80,
                "disk_healthy": metrics.get("system", {}).get("disk_percent", 100) < 80,
                "error_rate_healthy": metrics.get("application", {}).get("error_rate", 1) < 0.1,
                "components_healthy": sum(components_status.values()) >= 3,
                "credentials_normalized": components_status["credential_normalization"]
            },
            "recommendations": generate_health_recommendations(metrics, components_status)
        }
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

def generate_health_recommendations(metrics: Dict, components: Dict) -> List[str]:
    recommendations = []
    system_metrics = metrics.get("system", {})
    app_metrics = metrics.get("application", {})
    if system_metrics.get("cpu_percent", 0) > 80:
        recommendations.append("CPU使用率が高いです。負荷分散を検討してください。")
    if system_metrics.get("memory_percent", 0) > 80:
        recommendations.append("メモリ使用率が高いです。インスタンスサイズの増強を検討してください。")
    if system_metrics.get("disk_percent", 0) > 80:
        recommendations.append("ディスク使用率が高いです。ログローテーションを確認してください。")
    if app_metrics.get("error_rate", 0) > 0.05:
        recommendations.append("エラー率が高いです。ログを確認してください。")
    if not components.get("llm"):
        recommendations.append("LLMが読み込まれていません。OPENAI_API_KEYを確認してください。")
    if not components.get("vectorstore"):
        recommendations.append("ベクトルストアが読み込まれていません。")
    if not components.get("line_bot"):
        recommendations.append("LINE Botが設定されていません。認証情報を確認してください。")
    if not components.get("credential_normalization"):
        recommendations.append("認証情報の正規化が実行されていません。")
    if not recommendations:
        recommendations.append("システムは正常に動作しています。")
    return recommendations

# ★★★ ここから：要求通りの /healthz（基本版）★★★
@app.get("/healthz")
def health_check():
    """基本的なヘルスチェックエンドポイント（正規化対応）"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "rag-api",
            "version": "2.2.0"
        }
        components_ok = True
        if llm_instance is None:
            health_status.setdefault("warnings", []).append("LLM instance not loaded")
            components_ok = False
        if not normalized_line_token:
            health_status.setdefault("warnings", []).append("LINE credentials not configured")
        if system_monitor.credential_normalizations == 0:
            health_status.setdefault("warnings", []).append("Credential normalization not executed")
        if not components_ok:
            health_status["status"] = "degraded"
        health_status["credential_normalization"] = {
            "executed": system_monitor.credential_normalizations > 0,
            "count": system_monitor.credential_normalizations
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ★★★ LINE Bot診断 ★★★
@app.get("/line-bot-diagnostics")
def comprehensive_line_bot_diagnostics():
    try:
        diagnostics = {}
        env_vars = {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(normalized_line_token),
            "LINE_CHANNEL_SECRET": bool(normalized_line_secret),
            "LINE_LOGIN_CHANNEL_ID": bool(os.environ.get("LINE_LOGIN_CHANNEL_ID")),
            "LINE_LOGIN_CHANNEL_SECRET": bool(os.environ.get("LINE_LOGIN_CHANNEL_SECRET")),
            "LIFF_ID": bool(os.environ.get("LIFF_ID"))
        }
        def test_secret_access():
            try:
                from google.cloud import secretmanager
                client = secretmanager.SecretManagerServiceClient()
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
                secret_name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                response = client.access_secret_version(request={"name": secret_name})
                return len(response.payload.data) > 0
            except Exception as e:
                logger.error(f"Secret Manager test failed: {e}")
                return False
        def test_line_api():
            try:
                import requests
                if not normalized_line_token:
                    return False
                response = requests.get(
                    "https://api.line.me/v2/bot/info",
                    headers={"Authorization": f"Bearer {normalized_line_token}"},
                    timeout=10
                )
                return response.status_code == 200
            except Exception as e:
                logger.error(f"LINE API test failed: {e}")
                return False
        def test_webhook_endpoint():
            try:
                import requests
                service_name = os.environ.get('K_SERVICE', 'rag-api')
                region = os.environ.get('GOOGLE_CLOUD_REGION', 'asia-northeast1')
                webhook_url = f"https://{service_name}-190389115361.{region}.run.app/line/status"
                response = requests.get(webhook_url, timeout=10)
                return response.status_code == 200
            except Exception as e:
                logger.error(f"Webhook endpoint test failed: {e}")
                return False
        def test_line_sdk():
            return LINE_SDK_AVAILABLE
        diagnostics = {
            "environment_variables": env_vars,
            "secret_manager_access": test_secret_access(),
            "line_api_connection": test_line_api(),
            "webhook_endpoint": test_webhook_endpoint(),
            "line_sdk_available": test_line_sdk(),
            "credential_normalization": {
                "executed": system_monitor.credential_normalizations > 0,
                "count": system_monitor.credential_normalizations,
                "normalized_token_length": len(normalized_line_token) if normalized_line_token else 0,
                "normalized_secret_length": len(normalized_line_secret) if normalized_line_secret else 0
            }
        }
        critical_tests = [
            diagnostics["line_api_connection"],
            diagnostics["webhook_endpoint"], 
            diagnostics["line_sdk_available"],
            diagnostics["credential_normalization"]["executed"]
        ]
        all_tests_passed = all(critical_tests)
        recommendations = []
        if not diagnostics["secret_manager_access"]:
            recommendations.append("Secret Manager permissions確認")
        if not diagnostics["line_api_connection"]:
            recommendations.append("LINE Channel Access Token確認（正規化後）")
        if not diagnostics["webhook_endpoint"]:
            recommendations.append("Cloud Run deployment確認")
        if not diagnostics["line_sdk_available"]:
            recommendations.append("LINE Bot SDK installation確認")
        if not diagnostics["credential_normalization"]["executed"]:
            recommendations.append("認証情報正規化プロセス確認")
        return {
            "overall_status": "healthy" if all_tests_passed else "needs_attention",
            "diagnostics": diagnostics,
            "timestamp": datetime.now().isoformat(),
            "recommendations": [r for r in recommendations if r],
            "webhook_url": f"https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
            "liff_url": f"https://liff.line.me/{os.environ.get('LIFF_ID', 'not-set')}",
            "debug_info": {
                "service_url": f"https://rag-api-190389115361.asia-northeast1.run.app",
                "environment": os.environ.get("ENV", "unknown"),
                "version": "2.2.0 (ultra fast compatible)"
            }
        }
    except Exception as e:
        logger.error(f"LINE Bot diagnostics failed: {e}")
        return {"overall_status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

# ★★★ 簡易診断 ★★★
@app.get("/quick-diagnosis")
def quick_system_diagnosis():
    issues = []
    suggestions = []
    critical_issues = []
    
    if not normalized_line_token:
        critical_issues.append("LINE_CHANNEL_ACCESS_TOKEN not found or normalization failed")
        suggestions.append("Check LINE_CHANNEL_ACCESS_TOKEN in Secret Manager")
    if not normalized_line_secret:
        critical_issues.append("LINE_CHANNEL_SECRET not found or normalization failed") 
        suggestions.append("Check LINE_CHANNEL_SECRET in Secret Manager")
    if not llm_instance:
        issues.append("LLM not loaded")
        suggestions.append("Check OPENAI_API_KEY and model loading")
    if not vectorstore:
        issues.append("Vectorstore not loaded")
        suggestions.append("Check vectorstore initialization")
    if not rag_chain_template:
        issues.append("RAG chain not created")
        suggestions.append("Check RAG chain initialization")
    if system_monitor.credential_normalizations == 0:
        issues.append("Credential normalization not executed")
        suggestions.append("Check credential normalization process")
    
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        if cpu_percent > 90:
            issues.append("High CPU usage")
            suggestions.append("Consider scaling up resources")
        if memory.percent > 90:
            critical_issues.append("High memory usage")
            suggestions.append("Restart service or scale up memory")
    except:
        pass

    # ★ 追加：ULTRA FASTモードの閾値チェック（推奨チューニング）
    if ULTRA_FAST_MODE:
        if LINE_RESPONSE_TIMEOUT > 5:
            suggestions.append("LINE_RESPONSE_TIMEOUT を3秒以下に設定")
        if RAG_ULTRA_TIMEOUT > 6:
            suggestions.append("RAG_ULTRA_TIMEOUT を4秒以下に設定")
    
    if critical_issues:
        status = "🚨 Critical Issues Detected"
        priority_actions = critical_issues[:3]
    elif issues:
        status = "⚠️ Issues Detected"
        priority_actions = issues[:3]
    else:
        status = "✅ All Systems Operational"
        priority_actions = []
    
    return {
        "status": status,
        "critical_issues": critical_issues,
        "issues": issues,
        "priority_actions": priority_actions,
        "immediate_suggestions": suggestions[:5],
        "next_steps": [
            "Test rich menu buttons manually",
            "Check Cloud Run logs",
            "Verify LINE Developers settings",
            "Confirm credential normalization"
        ] if issues or critical_issues else [
            "System is healthy",
            "Monitor performance metrics",
            "Regular health checks recommended",
            "Credential normalization working properly"
        ],
        "emergency_commands": {
            "restart_richmenu": "python scripts/setup_fixed_richmenu.py",
            "redeploy_service": "gcloud builds submit --config cloudbuild.yaml",
            "check_logs": "gcloud logging read 'severity>=ERROR' --limit=20",
            "verify_credentials": "curl -H 'Authorization: Bearer TOKEN' https://api.line.me/v2/bot/info"
        } if issues else {},
        "credential_info": {
            "normalization_count": system_monitor.credential_normalizations,
            "token_length": len(normalized_line_token) if normalized_line_token else 0,
            "secret_length": len(normalized_line_secret) if normalized_line_secret else 0
        },
        "timestamp": datetime.now().isoformat()
    }

# ★★★ ULTRA FAST ステータス ★★★
@app.get("/ultra-fast-status")
def get_ultra_fast_status():
    """超高速モードの状態確認"""
    try:
        try:
            from rag.fast_rag_chain import get_ultra_fast_cache_stats  # type: ignore
            cache_stats = get_ultra_fast_cache_stats()
        except Exception:
            cache_stats = {"note": "Ultra fast RAG not available (using standard chain)"}
        return {
            "ultra_fast_mode": ULTRA_FAST_MODE,
            "timeout_settings": {
                "line_response": LINE_RESPONSE_TIMEOUT,
                "rag_processing": RAG_ULTRA_TIMEOUT,
                "target": "sub_30_seconds"
            },
            "cache_statistics": cache_stats,
            "performance_metrics": {
                "components_loaded": {
                    "llm": llm_instance is not None,
                    "vectorstore": vectorstore is not None,
                    "rag_chain": rag_chain_template is not None,
                },
                "optimization_enabled": [
                    "tokenizer_parallelism_disabled",
                    "langsmith_disabled",
                    "minimal_logging",
                    "fast_embeddings"
                ] if ULTRA_FAST_MODE else []
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

# ★★★ ULTRA FAST キャッシュクリア ★★★
@app.post("/clear-ultra-fast-cache")
def clear_ultra_fast_cache_endpoint():
    """超高速キャッシュをクリア"""
    try:
        try:
            from rag.fast_rag_chain import clear_ultra_fast_cache, get_ultra_fast_cache_stats  # type: ignore
        except Exception:
            return {
                "status": "error",
                "message": "Ultra fast RAG not available",
                "timestamp": datetime.now().isoformat()
            }
        before_stats = get_ultra_fast_cache_stats()
        clear_ultra_fast_cache()
        after_stats = get_ultra_fast_cache_stats()
        return {
            "status": "success",
            "before": before_stats,
            "after": after_stats,
            "message": "Ultra fast cache cleared successfully",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

# ★★★ メインエンドポイント ★★★
@app.get("/")
def comprehensive_root():
    uptime = (datetime.now() - system_monitor.startup_time).total_seconds()
    return {
        "service": {
            "name": "RAG FastAPI Backend with Comprehensive Monitoring",
            "version": "2.2.0",
            "status": "operational",
            "uptime_seconds": uptime,
            "uptime_formatted": str(timedelta(seconds=int(uptime)))
        },
        "components": {
            "llm": llm_instance is not None,
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None,
            "line_bot": bool(normalized_line_token and normalized_line_secret),
            "line_login": bool(os.environ.get("LINE_LOGIN_CHANNEL_ID")),
            "liff": bool(os.environ.get("LIFF_ID")),
            "credential_normalization": system_monitor.credential_normalizations > 0
        },
        "endpoints": {
            "chat": "/chat",
            "line_webhook": "/line/webhook",
            "line_login": "/line-login",
            "liff_app": "/liff",
            "health_check": "/system-health",
            "diagnostics": "/line-bot-diagnostics",
            "quick_diagnosis": "/quick-diagnosis",
            "ultra_fast_status": "/ultra-fast-status",
            "clear_ultra_fast_cache": "/clear-ultra-fast-cache",
            "healthz": "/healthz",
            "ops_healthz": "/ops/healthz",
            "debug_endpoints": {
                "line_debug": "/line-debug",
                "signature_test": "/test-line-signature",
                "webhook_test": "/line-webhook-test",
                "credentials_validation": "/line-credentials-validation"
            }
        },
        "monitoring": {
            "requests_processed": system_monitor.request_count,
            "errors_count": system_monitor.error_count,
            "error_rate": system_monitor.error_count / max(system_monitor.request_count, 1),
            "credential_normalizations": system_monitor.credential_normalizations
        },
        "environment": {
            "mode": os.environ.get("ENV", "development"),
            "cloud_run": bool(os.environ.get("K_SERVICE")),
            "region": os.environ.get("GOOGLE_CLOUD_REGION", "unknown")
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
def get_comprehensive_status():
    return {
        "llm_loaded": llm_instance is not None,
        "vectorstore_loaded": vectorstore is not None,
        "rag_chain_loaded": rag_chain_template is not None,
        "openai_api_key_set": bool(normalized_openai_key),
        "gcs_bucket": os.environ.get("GCS_BUCKET_NAME", "Not set"),
        "line_bot_configured": bool(normalized_line_token and normalized_line_secret),
        "line_login_configured": bool(
            os.environ.get("LINE_LOGIN_CHANNEL_ID") and 
            os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
        ),
        "liff_configured": bool(os.environ.get("LIFF_ID")),
        "langsmith_enabled": os.environ.get("LANGCHAIN_TRACING_V2") == "true",
        "credential_normalization": {
            "executed": system_monitor.credential_normalizations > 0,
            "count": system_monitor.credential_normalizations
        }
    }

# CORS preflight handling
@app.options("/{path:path}")
async def handle_options_requests(path: str):
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
            "Access-Control-Allow-Headers": "*",
        }
    )

# エラーハンドラー
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    system_monitor.record_error()
    logger.error(f"Global exception: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.now().isoformat(),
            "path": str(request.url.path)
        }
    )

# メイン実行
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=False,
        access_log=True,
        log_level="info"
    )
