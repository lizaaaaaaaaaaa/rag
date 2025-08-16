# main.py - 完全修正版（ULTRA FAST + リッチメニュー即座応答デバッグ一式）
# - 既存機能: 認証情報の正規化、LLM/RAG 初期化、包括的ヘルスチェック、LINE関連デバッグ
# - 追加機能: リッチメニュー即座応答の動作確認/診断エンドポイント群

import os
import sys
import traceback
import logging
from datetime import datetime
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

# --------------------------------
# ログ設定
# --------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", mode="a") if os.getenv("ENV") != "production" else logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# =========================
# 高速化・モード設定
# =========================
FAST_MODE = os.getenv("FAST_MODE", "false").lower() == "true"

# ULTRA FAST 追加設定
ULTRA_FAST_MODE = os.getenv("ULTRA_FAST_MODE", "true").lower() == "true"
RAG_TIMEOUT = int(os.getenv("RAG_TIMEOUT", "10"))
LINE_RESPONSE_TIMEOUT = int(os.getenv("LINE_RESPONSE_TIMEOUT", "3"))  # 3秒
RAG_ULTRA_TIMEOUT = int(os.getenv("RAG_ULTRA_TIMEOUT", "4"))          # 4秒
ENABLE_RESPONSE_CACHE = os.getenv("ENABLE_RESPONSE_CACHE", "false").lower() == "true"

if FAST_MODE:
    logger.info("🚀 Fast Mode Enabled")
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["DISABLE_LANGSMITH"] = "true"

if ULTRA_FAST_MODE:
    logger.info("🚀 Ultra Fast Mode Enabled - Sub-30-second response target")
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["DISABLE_LANGSMITH"] = "true"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["HF_DATASETS_CACHE"] = "/tmp/hf_cache"

# ------------------------------
# .env 読み込み（ローカルのみ）
# ------------------------------
if os.getenv("ENV") != "production":
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
        logger.info(">>> Loaded .env for local development")
    except Exception as e:
        logger.warning(f".env load skipped: {e}")
else:
    logger.info(">>> Running in production mode")

# =========================
# ユーティリティ
# =========================
from typing import Any

def normalize_credential(value: Any) -> str:
    """認証情報を安全に string へ正規化"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            logger.error("Failed to decode credential from bytes")
            return ""
    s = str(value).strip()
    if s.startswith("Bearer "):
        s = s[7:].strip()
    if s.startswith("b'") and s.endswith("'"):
        s = s[2:-1]
    return s

def mask_sensitive_data(value: str, show_chars: int = 10) -> str:
    if not value:
        return "未設定"
    return f"{value[:show_chars]}..." if len(value) > show_chars else "設定済み"

# =========================
# 認証情報の正規化 + ログ
# =========================
logger.info("==== Environment Variables Status ====")
logger.info("ENV: %s", os.environ.get("ENV"))

raw_openai_key = os.environ.get("OPENAI_API_KEY", "")
raw_line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
raw_line_secret = os.environ.get("LINE_CHANNEL_SECRET", "")

normalized_openai_key = normalize_credential(raw_openai_key)
normalized_line_token = normalize_credential(raw_line_token)
normalized_line_secret = normalize_credential(raw_line_secret)

logger.info("OPENAI_API_KEY: %s (normalized: %d chars)", mask_sensitive_data(raw_openai_key), len(normalized_openai_key))
logger.info("LINE_CHANNEL_ACCESS_TOKEN: %s (normalized: %d chars)", mask_sensitive_data(raw_line_token), len(normalized_line_token))
logger.info("LINE_CHANNEL_SECRET: %s (normalized: %d chars)", mask_sensitive_data(raw_line_secret), len(normalized_line_secret))

# 正規化結果を反映
if normalized_openai_key:
    os.environ["OPENAI_API_KEY"] = normalized_openai_key
if normalized_line_token:
    os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = normalized_line_token
if normalized_line_secret:
    os.environ["LINE_CHANNEL_SECRET"] = normalized_line_secret

# 追加ログ
logger.info("ULTRA_FAST_MODE: %s", ULTRA_FAST_MODE)
logger.info("LINE_RESPONSE_TIMEOUT: %s seconds", LINE_RESPONSE_TIMEOUT)
logger.info("RAG_ULTRA_TIMEOUT: %s seconds", RAG_ULTRA_TIMEOUT)
if ULTRA_FAST_MODE:
    logger.info("🎯 Target: Sub-30-second response for rich menu interactions")

# =========================
# LINE SDK チェック
# =========================
try:
    from linebot.v3 import WebhookHandler  # type: ignore
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 available")
except Exception:
    LINE_SDK_AVAILABLE = False
    logger.warning("⚠️ LINE Bot SDK not available")

# =========================
# FastAPI アプリ
# =========================
app = FastAPI(
    title="RAG FastAPI Backend (Ultra Fast)",
    description="RAG + LLM + LINE Bot + Monitoring",
    version="2.3.0",
    docs_url="/docs" if os.getenv("ENV") != "production" else None,
    redoc_url="/redoc" if os.getenv("ENV") != "production" else None,
)

# Trusted Host（本番）
if os.getenv("ENV") == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "rag-api-190389115361.asia-northeast1.run.app",
            "*.run.app",
            "localhost",
        ],
    )

# CORS
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
        "*",  # 開発時のみ
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# セキュリティヘッダー
@app.middleware("http")
async def add_comprehensive_security_headers(request: Request, call_next):
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

# パフォーマンス計測
@app.middleware("http")
async def monitor_performance(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    process_time = (datetime.now() - start_time).total_seconds()
    if process_time > 5.0:
        logger.warning(f"Slow request: {request.method} {request.url.path} took {process_time:.2f}s")
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Timestamp"] = start_time.isoformat()
    return response

# =========================
# システム監視
# =========================
class SystemMonitor:
    def __init__(self):
        self.startup_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
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
            disk = psutil.disk_usage("/")
            process = psutil.Process()
            process_memory = process.memory_info()
            return {
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "memory_total_gb": memory.total / (1024 ** 3),
                    "memory_available_gb": memory.available / (1024 ** 3),
                    "disk_percent": (disk.used / disk.total) * 100,
                    "disk_total_gb": disk.total / (1024 ** 3),
                    "disk_free_gb": disk.free / (1024 ** 3),
                },
                "process": {
                    "memory_rss_mb": process_memory.rss / (1024 ** 2),
                    "memory_vms_mb": process_memory.vms / (1024 ** 2),
                    "cpu_percent": process.cpu_percent(),
                    "threads": process.num_threads(),
                    "open_files": len(process.open_files()),
                },
                "application": {
                    "uptime_seconds": (datetime.now() - self.startup_time).total_seconds(),
                    "request_count": self.request_count,
                    "error_count": self.error_count,
                    "error_rate": self.error_count / max(self.request_count, 1),
                    "credential_normalizations": self.credential_normalizations,
                },
            }
        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            return {"error": str(e)}

system_monitor = SystemMonitor()

if normalized_openai_key or normalized_line_token or normalized_line_secret:
    system_monitor.record_credential_normalization()

# =========================
# グローバル（LLM/RAG）
# =========================
vectorstore = None
rag_chain_template = None
llm_instance = None

# =========================
# 起動処理
# =========================
@app.on_event("startup")
async def enhanced_startup():
    global vectorstore, rag_chain_template, llm_instance
    startup_time = datetime.now()
    logger.info("🚀 Enhanced startup process initiated")
    logger.info("=" * 60)

    # 1. リソースログ
    try:
        logger.info("📊 System Resource Check:")
        logger.info(f"  CPU cores: {psutil.cpu_count()}")
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        logger.info(f"  Memory: total {memory.total/(1024**3):.2f} GB / avail {memory.available/(1024**3):.2f} GB / {memory.percent:.1f}%")
        logger.info(f"  Disk: {(disk.used/disk.total)*100:.1f}% used")
    except Exception as e:
        logger.error(f"❌ System resource check failed: {e}")

    # 2. Cloud Run info
    try:
        cloud_run_info = {
            "service_name": os.environ.get("K_SERVICE", "local"),
            "revision": os.environ.get("K_REVISION", "local"),
            "configuration": os.environ.get("K_CONFIGURATION", "local"),
            "region": os.environ.get("GOOGLE_CLOUD_REGION", "unknown"),
            "project": os.environ.get("GOOGLE_CLOUD_PROJECT", "unknown"),
        }
        for k, v in cloud_run_info.items():
            logger.info(f"  {k}: {v}")
    except Exception as e:
        logger.error(f"❌ Cloud Run info collection failed: {e}")

    # 3. LLM
    try:
        logger.info("🧠 Loading LLM...")
        from llm.llm_runner import load_llm  # ユーザー環境のロード関数
        llm, tokenizer, max_tokens = load_llm()
        llm_instance = llm
        logger.info(f"✅ LLM loaded: {type(llm).__name__}")
        try:
            _ = llm.invoke("こんにちは") if hasattr(llm, "invoke") else llm("こんにちは")
            logger.info("✅ LLM test successful")
        except Exception as e:
            logger.warning(f"⚠️ LLM test warning: {e}")
    except Exception as e:
        logger.error(f"❌ LLM load failed: {e}")
        logger.error(traceback.format_exc())
        llm_instance = None

    # 4. Vectorstore
    try:
        logger.info("🔍 Loading Vectorstore...")
        from rag.ingested_text import load_vectorstore
        vectorstore = load_vectorstore()
        if vectorstore:
            logger.info("✅ Vectorstore loaded")
            try:
                _ = vectorstore.similarity_search("住宅", k=1)
                logger.info("✅ Vectorstore test successful")
            except Exception as e:
                logger.warning(f"⚠️ Vectorstore test warning: {e}")
        else:
            logger.warning("⚠️ Vectorstore is None")
    except Exception as e:
        logger.warning(f"⚠️ Vectorstore load failed: {e}")
        vectorstore = None

    # 5. RAG チェーン
    try:
        if vectorstore and llm_instance:
            logger.info("⛓️ Building RAG chain...")
            if ULTRA_FAST_MODE:
                try:
                    from rag.fast_rag_chain import get_ultra_fast_rag_chain  # type: ignore
                    rag_chain_template = get_ultra_fast_rag_chain(vectorstore=vectorstore, return_source=True)
                    logger.info("✅ Ultra fast RAG chain created")
                except Exception as import_err:
                    logger.warning(f"⚠️ Ultra fast chain not available, fallback: {import_err}")
                    from rag.ingested_text import get_rag_chain
                    rag_chain_template = get_rag_chain(vectorstore=vectorstore, return_source=True)
                    logger.info("✅ Standard RAG chain created")
            else:
                from rag.ingested_text import get_rag_chain
                rag_chain_template = get_rag_chain(vectorstore=vectorstore, return_source=True)
                logger.info("✅ Standard RAG chain created")

            # テスト
            try:
                t0 = datetime.now()
                _ = rag_chain_template.invoke({"query": "テスト"})
                logger.info(f"✅ RAG chain test ({(datetime.now()-t0).total_seconds():.2f}s)")
            except Exception as e:
                logger.warning(f"⚠️ RAG chain test warning: {e}")

        elif vectorstore:
            logger.info("⛓️ Building search-only chain...")
            class SimpleSearchChain:
                def __init__(self, vectorstore):
                    self.vectorstore = vectorstore
                    self.retriever = vectorstore.as_retriever()
                def invoke(self, inputs: Dict[str, Any]):
                    query = inputs.get("query", "")
                    docs = self.retriever.invoke(query)
                    if docs:
                        body = "関連情報:\n\n"
                        for i, doc in enumerate(docs[:3], 1):
                            content = doc.page_content[:300]
                            source = doc.metadata.get("source", "不明")
                            page = doc.metadata.get("page", "?")
                            body += f"{i}. {content}...\n出典: {source} (p{page})\n\n"
                    else:
                        body = "関連する文書が見つかりませんでした。"
                    return {"result": body, "source_documents": docs[:3] if docs else []}
            rag_chain_template = SimpleSearchChain(vectorstore)
            logger.info("✅ Search-only chain created")
        else:
            rag_chain_template = None
            logger.warning("⚠️ No vectorstore available for RAG chain")
    except Exception as e:
        logger.error(f"❌ RAG chain creation failed: {e}")
        logger.error(traceback.format_exc())
        rag_chain_template = None

    # 6. LINE Bot 設定確認
    try:
        logger.info("📱 LINE Bot Configuration Check:")
        checks = {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(normalized_line_token),
            "LINE_CHANNEL_SECRET": bool(normalized_line_secret),
            "LINE_LOGIN_CHANNEL_ID": bool(os.environ.get("LINE_LOGIN_CHANNEL_ID")),
            "LINE_LOGIN_CHANNEL_SECRET": bool(os.environ.get("LINE_LOGIN_CHANNEL_SECRET")),
            "LIFF_ID": bool(os.environ.get("LIFF_ID")),
        }
        for k, v in checks.items():
            logger.info(f"  {k}: {'✅ Set' if v else '❌ Not set'}")
    except Exception as e:
        logger.error(f"❌ LINE Bot configuration check failed: {e}")

    # 7. 起動完了
    startup_duration = (datetime.now() - startup_time).total_seconds()
    logger.info("=" * 60)
    logger.info("🎉 Enhanced Startup Complete!")
    logger.info(f"⏱️ Startup duration: {startup_duration:.2f} seconds")
    logger.info("=" * 60)

# =========================
# ルーター登録
# =========================
try:
    from api.routers import upload, chat, google_oauth, healthz, line_bot, line_login  # type: ignore
    app.include_router(upload.router, prefix="/upload", tags=["upload"])
    app.include_router(chat.router, prefix="/chat", tags=["chat"])
    app.include_router(google_oauth.router, tags=["auth"])
    app.include_router(healthz.router, prefix="/ops", tags=["healthz-ops"])
    app.include_router(line_bot.router, tags=["line"])
    app.include_router(line_login.router, tags=["line-login"])
except Exception as e:
    logger.warning(f"Router include warning: {e}")

# 静的ファイル（PDF）
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

# =========================
# 既存のデバッグ/ヘルス系 Endpoint
# =========================
@app.get("/line-debug")
def line_debug_endpoint():
    try:
        return {
            "line_credentials": {
                "access_token_set": bool(normalized_line_token),
                "channel_secret_set": bool(normalized_line_secret),
                "access_token_length": len(normalized_line_token) if normalized_line_token else 0,
                "secret_length": len(normalized_line_secret) if normalized_line_secret else 0,
                "access_token_preview": (normalized_line_token[:20] + "...") if normalized_line_token else "未設定",
                "secret_preview": (normalized_line_secret[:10] + "...") if normalized_line_secret else "未設定",
            },
            "webhook_info": {
                "webhook_url": "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
                "liff_url": f"https://liff.line.me/{os.environ.get('LIFF_ID', 'not-set')}",
            },
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "environment": os.environ.get("ENV", "unknown"),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/test-line-signature")
def test_line_signature():
    try:
        if not normalized_line_secret:
            return {"error": "LINE_CHANNEL_SECRET not found or normalized"}
        test_body = '{"events":[],"destination":"test"}'
        hash_ = hmac.new(normalized_line_secret.encode("utf-8"), test_body.encode("utf-8"), hashlib.sha256).digest()
        signature = base64.b64encode(hash_).decode("utf-8")
        return {
            "test_body": test_body,
            "generated_signature": signature,
            "signature_format": f"X-Line-Signature: {signature}",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/system-health")
def comprehensive_system_health():
    try:
        metrics = system_monitor.get_system_metrics()
        components_status = {
            "llm": llm_instance is not None,
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None,
            "line_bot": bool(normalized_line_token and normalized_line_secret),
        }
        all_critical_healthy = all([
            components_status["llm"] or components_status["vectorstore"],
            metrics.get("system", {}).get("cpu_percent", 100) < 90,
            metrics.get("system", {}).get("memory_percent", 100) < 90,
        ])
        status = "healthy" if all_critical_healthy else "degraded"
        return {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "system_metrics": metrics,
            "components": components_status,
            "ultra_fast_mode": {
                "enabled": ULTRA_FAST_MODE,
                "line_timeout": LINE_RESPONSE_TIMEOUT,
                "rag_timeout": RAG_ULTRA_TIMEOUT,
                "target_response_time": "sub_30_seconds",
            },
        }
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/healthz")
def health_check():
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "rag-api",
            "version": "2.3.0",
        }
        if llm_instance is None:
            health_status.setdefault("warnings", []).append("LLM instance not loaded")
            health_status["status"] = "degraded"
        if not normalized_line_token or not normalized_line_secret:
            health_status.setdefault("warnings", []).append("LINE credentials not configured")
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "timestamp": datetime.now().isoformat()}

# =========================
# ★ 追加：リッチメニュー即座応答デバッグ系 Endpoint
# =========================
@app.get("/richmenu-instant-status")
def get_richmenu_instant_status():
    """リッチメニュー即座応答の状態確認"""
    try:
        # 遅延 import（循環参照回避）
        from api.routers.line_bot import detect_richmenu_action_instant, get_instant_richmenu_response  # type: ignore

        test_messages = [
            "AI相談",
            "AI住まいサイト",
            "資料請求",
            "展示場来場予約",
            "資金計画",
            "チャット相談",
        ]

        results = {}
        for message in test_messages:
            action = detect_richmenu_action_instant(message)
            response = get_instant_richmenu_response(action)
            results[message] = {
                "detected_action": action,
                "is_instant": action != "general",
                "response_length": len(response),
                "response_preview": (response[:100] + "...") if len(response) > 100 else response,
            }

        instant_count = sum(1 for r in results.values() if r["is_instant"])
        total_count = len(results)

        return {
            "status": "ok",
            "instant_response_rate": f"{instant_count}/{total_count}",
            "success_rate": instant_count / total_count if total_count else 0.0,
            "all_instant": instant_count == total_count,
            "results": results,
            "recommendations": [
                "すべてのメニューが即座応答対応済み" if instant_count == total_count else "一部のメニューで改善が必要",
                "LINE Developersコンソールでリッチメニュー設定を確認",
                "メッセージテキストが完全一致しているか確認",
            ],
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

@app.post("/test-richmenu-message")
async def test_richmenu_message(request: Dict[str, Any]):
    """リッチメニューメッセージのテスト"""
    try:
        message = request.get("message", "") if isinstance(request, dict) else ""
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")

        from api.routers.line_bot import detect_richmenu_action_instant, get_instant_richmenu_response  # type: ignore

        start = datetime.now()
        action = detect_richmenu_action_instant(message)
        response = get_instant_richmenu_response(action)
        processing_time = (datetime.now() - start).total_seconds()

        return {
            "message": message,
            "detected_action": action,
            "is_instant": action != "general",
            "response": response,
            "processing_time_seconds": processing_time,
            "is_fast": processing_time < 0.1,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/line-richmenu-diagnostics")
def line_richmenu_diagnostics():
    """LINE リッチメニューの包括的診断"""
    try:
        from api.routers.line_bot import (
            detect_richmenu_action_instant,
            get_instant_richmenu_response,
            INSTANT_RICHMENU_RESPONSES,
            monitor,
        )  # type: ignore

        # 1) 判定テスト
        test_cases = [
            {"input": "AI相談", "expected": "ai_consultation"},
            {"input": "AI住まいサイト", "expected": "ai_site"},
            {"input": "資料請求", "expected": "document_request"},
            {"input": "展示場来場予約", "expected": "exhibition_reservation"},
            {"input": "資金計画", "expected": "finance_planning"},
            {"input": "チャット相談", "expected": "chat_consultation"},
            {"input": "こんにちは", "expected": "greeting"},
            {"input": "普通の質問", "expected": "general"},
        ]
        message_tests = []
        for t in test_cases:
            actual = detect_richmenu_action_instant(t["input"])
            is_correct = actual == t["expected"]
            message_tests.append({
                "input": t["input"],
                "expected": t["expected"],
                "actual": actual,
                "is_correct": is_correct,
                "has_response": actual in INSTANT_RICHMENU_RESPONSES,
            })

        # 2) 応答品質
        response_quality: Dict[str, Any] = {}
        for action, response in INSTANT_RICHMENU_RESPONSES.items():
            response_quality[action] = {
                "length": len(response),
                "has_emoji": any(ord(c) > 127 for c in response),
                "has_structure": ("・" in response) or ("📋" in response) or ("💡" in response),
                "preview": (response[:100] + "...") if len(response) > 100 else response,
            }

        # 3) パフォーマンス統計
        stats = getattr(monitor, "stats", {})
        performance_stats = {
            "instant_responses": stats.get("instant_responses", 0),
            "richmenu_responses": stats.get("richmenu_responses", 0),
            "total_messages": stats.get("message_events", 0),
            "instant_response_rate": 0,
        }
        if performance_stats["total_messages"] > 0:
            performance_stats["instant_response_rate"] = performance_stats["instant_responses"] / performance_stats["total_messages"]

        # 4) 設定状況
        configuration_status = {
            "line_bot_configured": bool(normalized_line_token and normalized_line_secret),
            "instant_responses_available": len(INSTANT_RICHMENU_RESPONSES),
            "detection_patterns": len([t for t in message_tests if t["is_correct"]]),
            "webhook_endpoint": "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
        }

        # 5) 問題診断
        issues, recommendations = [], []
        incorrect = [t for t in message_tests if not t["is_correct"]]
        if incorrect:
            issues.append(f"{len(incorrect)}個のメッセージで判定ミス")
            recommendations.append("detect_richmenu_action_instant関数の修正が必要")
        if not configuration_status["line_bot_configured"]:
            issues.append("LINE Bot認証情報が不完全")
            recommendations.append("LINE_CHANNEL_ACCESS_TOKEN と LINE_CHANNEL_SECRET を確認")
        if performance_stats["instant_response_rate"] < 0.8:
            issues.append("即座応答率が低い")
            recommendations.append("リッチメニューの設定とメッセージテキストを確認")
        if not issues:
            recommendations.append("すべての診断項目が正常です")

        return {
            "overall_status": "healthy" if not issues else "needs_attention",
            "message_detection_tests": {
                "total": len(message_tests),
                "correct": len([t for t in message_tests if t["is_correct"]]),
                "success_rate": len([t for t in message_tests if t["is_correct"]]) / len(message_tests) if message_tests else 0,
                "details": message_tests,
            },
            "response_quality": response_quality,
            "performance_stats": performance_stats,
            "configuration_status": configuration_status,
            "issues": issues,
            "recommendations": recommendations,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Richmenu diagnostics error: {e}")
        return {"overall_status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

@app.post("/force-richmenu-cache-clear")
def force_richmenu_cache_clear():
    """リッチメニュー関連のキャッシュを強制クリア"""
    try:
        try:
            from api.routers.line_bot import _message_response_cache  # type: ignore
            cache_size_before = len(_message_response_cache)
            _message_response_cache.clear()
            cache_cleared = cache_size_before
        except Exception:
            cache_cleared = 0

        try:
            import gc
            gc.collect()
            gc_collected = True
        except Exception:
            gc_collected = False

        return {
            "status": "success",
            "message_cache_cleared": cache_cleared,
            "gc_collected": gc_collected,
            "timestamp": datetime.now().isoformat(),
            "note": "リッチメニューの動作が改善される可能性があります",
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}
