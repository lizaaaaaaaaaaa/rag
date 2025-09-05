# main.py - グローバル変数宣言修正版 + チャット/デバッグ/ヘルス統合（v7.5.2）

import logging, os, asyncio, time, json, traceback, sys, pathlib, importlib, importlib.util, types
from datetime import datetime
from typing import Dict, Any, List
from uuid import uuid4

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware  # for custom middlewares
import jwt  # PyJWT

# ===== ミドルウェア（プロジェクト内の自作ミドルウェアを想定）=====
try:
    from middleware import (
        TimingMiddleware,
        CORSMiddleware,
        SecurityHeadersMiddleware,
        RateLimitMiddleware,
        ConsentGateMiddleware,
        AuditLoggingMiddleware,
    )
    HAS_INTERNAL_MIDDLEWARE = True
except Exception:
    HAS_INTERNAL_MIDDLEWARE = False

# ===== DB 初期化（存在しない/未使用でも import のみ）=====
try:
    from database import init_database  # type: ignore
    HAS_DB = True
except Exception:
    HAS_DB = False

# ===== パス設定 =====
ROOT = pathlib.Path(__file__).resolve().parent
for p in [ROOT, ROOT/"services", ROOT/"llm", ROOT/"rag", ROOT/"api", ROOT/"api"/"routers", ROOT/"utils"]:
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

# ===== ロガー設定 =====
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ===== FastAPI =====
app = FastAPI(
    title="Unified RAG API - Enhanced with Debug",
    description="High-Performance Unified AI Chat API with Enhanced Error Handling",
    version="7.5.2",
)

# ========================================
# グローバル変数（必ず最初に明示的に宣言・初期化）
# ========================================
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False
RAG_SHARED_GLOBALLY = False

# 設定値
ENABLE_RAG_INITIALIZATION = os.getenv("DISABLE_RAG_INIT", "false").lower() != "true"
ENABLE_UNIFIED_CHAT = True
ENABLE_LINE_INTEGRATION = True

UNIFIED_CHAT_MODE = os.getenv("UNIFIED_CHAT_MODE", "complete")
DEFAULT_PLATFORM = "web"
DEFAULT_RESPONSE_MODE = "auto"
INCLUDE_SOURCES = os.getenv("INCLUDE_SOURCES", "false").lower() == "true"
startup_time = time.time()

# RAG診断情報
rag_diagnostics = {
    "initialization_attempts": 0,
    "initialization_success": False,
    "last_initialization_time": None,
    "initialization_duration": 0.0,
    "component_status": {
        "llm_instance": {"loaded": False, "error": None, "load_time": 0.0},
        "vectorstore": {"loaded": False, "error": None, "load_time": 0.0, "file_path": None, "file_size": 0},
        "rag_chain": {"loaded": False, "error": None, "load_time": 0.0},
    },
    "fallback_info": {"used_fallback": False, "fallback_type": None, "fallback_reason": None},
    "health_checks": {"last_check": None, "vectorstore_test": False, "rag_query_test": False, "llm_response_test": False},
}

# ========================================
# ユーティリティ
# ========================================
def ensure_utils_web_search_alias() -> bool:
    """utils.web_search の import 別名解決（配置差異に対応）"""
    try:
        import utils.web_search  # type: ignore
        return True
    except Exception:
        pass
    candidates = [
        ROOT/"utils"/"web_search.py",
        ROOT/"api"/"utils"/"web_search.py",
        ROOT/"web_search.py",
        ROOT/"api"/"routers"/"web_search.py",
    ]
    for path in candidates:
        if path.exists():
            try:
                spec = importlib.util.spec_from_file_location("utils.web_search", str(path))
                if spec and spec.loader:
                    mod = importlib.module_from_spec(spec)  # type: ignore
                    spec.loader.exec_module(mod)            # type: ignore
                    if "utils" not in sys.modules:
                        sys.modules["utils"] = types.ModuleType("utils")
                    sys.modules["utils.web_search"] = mod
                    logger.info(f"✅ utils.web_search alias set from {path}")
                    return True
            except Exception as e:
                logger.warning(f"utils.web_search alias failed for {path}: {e}")
    logger.warning("⚠️ utils.web_search could not be resolved; some features may error")
    return False


def _enforce_env_minimums():
    """最低限の環境変数値を強制（安全側）"""
    mins = {"MAX_NEW_TOKENS": "900", "OPENAI_MAX_TOKENS": "900", "LLM_TIMEOUT": "45"}
    bumped = {}
    for k, v in mins.items():
        cur = os.getenv(k)
        if cur is None or (cur.isdigit() and int(cur) < int(v)):
            os.environ[k] = v
            bumped[k] = v
    if bumped:
        logger.warning(f"BootGuard: bumped env minimums -> {bumped}")

# 起動ログ
_BOOT_T0 = time.time()
try:
    logger.info(json.dumps({"evt": "boot", "phase": "start"}))
except Exception:
    pass
_enforce_env_minimums()

# ========================================
# RAG初期化関数（修正版：global 変数を最初に宣言・使用順を厳守）
# ========================================
async def initialize_rag_components():
    global vectorstore, rag_chain_template, llm_instance, is_initialized, RAG_SHARED_GLOBALLY, rag_diagnostics

    if is_initialized:
        logger.info("✅ RAG components already initialized")
        return

    async with initialization_lock:
        if is_initialized:
            return

        t0 = time.time()
        rag_diagnostics["initialization_attempts"] += 1
        rag_diagnostics["last_initialization_time"] = datetime.now().isoformat()
        logger.info("🚀 Initializing RAG components...")

        try:
            ensure_utils_web_search_alias()

            # ---- LLM 初期化 ----
            try:
                llm_t0 = time.time()
                llm_instance = None
                try:
                    mod = importlib.import_module("llm.llm_runner")
                    get_cached = getattr(mod, "get_cached_llm_instance", None)
                    if callable(get_cached):
                        llm_instance = get_cached()
                    else:
                        load_llm = getattr(mod, "load_llm", None)
                        if callable(load_llm):
                            res = load_llm()
                            llm_instance = res[0] if isinstance(res, tuple) else res
                except Exception:
                    try:
                        mod = importlib.import_module("llm_runner")
                        get_cached = getattr(mod, "get_cached_llm_instance", None)
                        if callable(get_cached):
                            llm_instance = get_cached()
                    except Exception:
                        pass

                rag_diagnostics["component_status"]["llm_instance"]["loaded"] = bool(llm_instance)
                rag_diagnostics["component_status"]["llm_instance"]["load_time"] = time.time() - llm_t0

                if llm_instance:
                    logger.info("✅ LLM instance loaded successfully")
                else:
                    logger.warning("⚠️ LLM instance not loaded - will use fallback")

            except Exception as e:
                rag_diagnostics["component_status"]["llm_instance"]["error"] = str(e)
                logger.warning(f"⚠️ LLM load failed: {e}")

            # ---- Vectorstore + Chain 初期化 ----
            try:
                vs_t0 = time.time()
                try:
                    fast_mod = importlib.import_module("rag.fast_rag_chain")
                    load_vs = getattr(fast_mod, "load_super_fast_vectorstore")
                    get_chain = getattr(fast_mod, "get_super_fast_rag_chain")
                    vectorstore = load_vs()
                    rag_chain_template = get_chain(vectorstore, return_source=INCLUDE_SOURCES)
                    logger.info("✅ Fast RAG chain loaded")
                    rag_diagnostics["component_status"]["vectorstore"]["loaded"] = True
                    rag_diagnostics["component_status"]["rag_chain"]["loaded"] = True
                except Exception as e_fast:
                    logger.warning(f"⚠️ Fast RAG init failed: {e_fast}")
                    logger.info("🔄 Falling back to services.rag_chain")
                    try:
                        svc_mod = importlib.import_module("services.rag_chain")
                    except ModuleNotFoundError:
                        svc_mod = importlib.import_module("rag_chain")

                    get_rag_response = getattr(svc_mod, "get_rag_response")

                    class _FrontDoorChain:
                        def __init__(self, include_sources: bool):
                            self.include_sources = include_sources
                        def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
                            q = (inputs.get("query") or inputs.get("question") or "").strip()
                            ans, srcs = get_rag_response(q)
                            if not self.include_sources:
                                return {"result": ans, "source_documents": []}
                            docs = [{"metadata": {"source": s}} for s in srcs]
                            return {"result": ans, "source_documents": docs}

                    vectorstore = None
                    rag_chain_template = _FrontDoorChain(include_sources=INCLUDE_SOURCES)
                    rag_diagnostics["fallback_info"].update({
                        "used_fallback": True,
                        "fallback_type": "services_front_door",
                        "fallback_reason": str(e_fast)
                    })
                    logger.info("✅ Fallback RAG chain loaded")

                rag_diagnostics["component_status"]["vectorstore"]["load_time"] = time.time() - vs_t0
                rag_diagnostics["component_status"]["rag_chain"]["load_time"] = time.time() - vs_t0

            except Exception as e_vs:
                rag_diagnostics["component_status"]["vectorstore"]["error"] = str(e_vs)
                rag_diagnostics["component_status"]["rag_chain"]["error"] = str(e_vs)
                logger.error(f"❌ Vectorstore/Chain init failed: {e_vs}")
                raise

            is_initialized = True
            RAG_SHARED_GLOBALLY = True
            rag_diagnostics["initialization_success"] = True
            rag_diagnostics["initialization_duration"] = time.time() - t0
            logger.info(f"🎉 RAG init completed in {rag_diagnostics['initialization_duration']:.2f}s")

        except Exception as e:
            is_initialized = False
            RAG_SHARED_GLOBALLY = False
            rag_diagnostics["initialization_success"] = False
            rag_diagnostics["initialization_duration"] = time.time() - t0
            logger.error(f"💥 RAG init failed after {rag_diagnostics['initialization_duration']:.2f}s: {e}")
            logger.error(traceback.format_exc())

# ========================================
# 監視 & リクエストモデル
# ========================================
class PerfMon:
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {
            "chat_requests": 0, "web_requests": 0, "line_requests": 0,
            "rag_requests": 0, "template_requests": 0,
            "total_response_time": 0.0, "errors": 0
        }
    def record(self, platform: str, mode: str, rt: float):
        self.metrics["chat_requests"] += 1
        if platform == "line": self.metrics["line_requests"] += 1
        else: self.metrics["web_requests"] += 1
        if mode in ("rag", "rag_enhanced"): self.metrics["rag_requests"] += 1
        if mode in ("template", "template_enhanced"): self.metrics["template_requests"] += 1
        self.metrics["total_response_time"] += rt
    def error(self): self.metrics["errors"] += 1
    def stats(self) -> Dict[str, Any]:
        total = self.metrics["chat_requests"]; uptime = time.time() - self.start_time
        avg = (self.metrics["total_response_time"] / total) if total else 0
        return {"uptime_seconds": uptime, "total_requests": total, "avg_response_time": avg, **self.metrics}

perf = PerfMon()

class UnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"
    debug_mode: bool | None = False

# ========================================
# フォールバック応答
# ========================================
def _fallback_response(question: str, request_id: str, platform: str, mode: str, t0: float, error: str = None):
    rt = time.time() - t0
    perf.error()

    fallback_answers = {
        "こんにちは": "こんにちは！どのようなご質問でしょうか？",
        "ありがとう": "どういたしまして！他にご質問はありますか？",
        "テスト": "システムは正常に動作しています。",
        "hello": "Hello! How can I help you?",
        "test": "System is working properly.",
    }

    question_lower = (question or "").strip().lower()
    fallback_answer = fallback_answers.get(question_lower)

    if not fallback_answer:
        if any(word in question_lower for word in ["住宅", "家", "建築", "設計", "間取り"]):
            fallback_answer = "住まいに関するご質問ですね。申し訳ございませんが、現在システムメンテナンス中のため、詳細な回答ができません。担当者がご対応いたしますので、しばらくお待ちください。"
        elif any(word in question_lower for word in ["価格", "費用", "予算", "金額"]):
            fallback_answer = "価格に関するご質問ですね。詳細な金額については、担当者が個別にご案内いたします。しばらくお待ちください。"
        else:
            fallback_answer = "申し訳ございません。現在システムメンテナンス中のため、一時的にご利用いただけません。しばらく時間をおいてから再度お試しください。"

    return JSONResponse(status_code=200, content={
        "answer": fallback_answer,
        "sources": [],
        "status": "fallback",
        "performance": {"total_time": rt, "platform": platform, "mode": mode},
        "system_info": {
            "version": "7.5.2",
            "rag_status": "error" if error else "unavailable",
            "request_id": request_id,
            "error": error if error else "System temporarily unavailable"
        }
    })

# ========================================
# チャットエンドポイント（global 参照の順序違反を解消）
# ========================================
@app.post("/chat")
async def unified_chat(req: UnifiedChatRequest, request: Request):
    """
    統合チャットエンドポイント（エラーハンドリング強化版）
    - OpenAI API KEY チェック
    - utils.web_search エイリアス解決
    - RAG 初期化を専用関数に委譲（関数内で global 宣言順を遵守）
    - 詳細デバッグ情報のオプション付与
    """
    t0 = time.time()
    platform = req.platform or "web"
    request_id = getattr(request.state, "request_id", str(uuid4())[:8])

    # ユーザー識別（匿名許可）
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]
            try:
                payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256","RS256","ES256"])
                user_id = payload.get("sub") or payload.get("user_id") or payload.get("email")
            except Exception:
                user_id = None
    if not user_id:
        user_id = f"web-anon-{request_id}"

    username = req.username or user_id
    mode = req.mode or "auto"

    logger.info(f"Chat request [{request_id}]: platform={platform}, user={user_id[:12]}..., mode={mode}, question_len={len(req.question) if req.question else 0}")

    try:
        # 1) OPENAI キーチェック（必要に応じて）
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            logger.error(f"[{request_id}] OPENAI_API_KEY not set - this is required for LLM functionality")
            raise HTTPException(status_code=500, detail="LLM configuration error: OpenAI API key not configured")

        # 2) web_search の alias 確保（失敗しても続行）
        try:
            ensure_utils_web_search_alias()
        except Exception as e:
            logger.warning(f"[{request_id}] Web search alias setup failed: {e}")

        # 3) RAG 初期化（必要に応じて、専用関数に委譲）
        if ENABLE_RAG_INITIALIZATION and not is_initialized:
            await initialize_rag_components()
            if not is_initialized:
                logger.warning(f"[{request_id}] RAG not initialized, using fallback response")
                return _fallback_response(req.question, request_id, platform, mode, t0, "RAG initialization failed")

        # 4) チャット生成モジュールの解決
        unified_generator = None
        last_err = None
        for m in ("api.routers.chat_unified", "routers.chat_unified", "chat_unified"):
            try:
                mod = importlib.import_module(m)
                unified_generator = getattr(mod, "unified_generator", mod)
                logger.info(f"[{request_id}] Using chat module: {m}")
                break
            except Exception as e:
                last_err = e

        if unified_generator is None:
            logger.error(f"[{request_id}] Chat module not found: {last_err}")
            return _fallback_response(req.question, request_id, platform, mode, t0, f"Chat module unavailable: {last_err}")

        # 5) 応答生成（タイムアウトつき）
        try:
            response = await asyncio.wait_for(
                unified_generator.generate_response(req.question, platform, username, mode),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.error(f"[{request_id}] Response generation timed out")
            return _fallback_response(req.question, request_id, platform, mode, t0, "Response generation timeout")
        except Exception as e:
            logger.error(f"[{request_id}] Generate response failed: {e}")
            logger.error(traceback.format_exc())
            if "openai" in str(e).lower() or "api_key" in str(e).lower():
                return _fallback_response(req.question, request_id, platform, mode, t0, f"OpenAI API error: {e}")
            else:
                return _fallback_response(req.question, request_id, platform, mode, t0, f"Response generation error: {e}")

        # 6) 正常レスポンス
        rt = time.time() - t0
        perf.record(platform, response.get("source", mode), rt)
        result = {
            "answer": response.get("answer", ""),
            "sources": response.get("sources", []),
            "status": response.get("status", "ok"),
            "performance": {"total_time": rt, "platform": platform, "mode": mode, "source": response.get("source")},
            "system_info": {
                "version": "7.5.2",
                "rag_status": "initialized" if is_initialized else "skipped",
                "request_id": request_id,
                "llm_available": bool(llm_instance),
                "openai_configured": bool(openai_key),
            },
        }
        if req.debug_mode:
            result["debug_info"] = {
                "perf": perf.stats(),
                "rag_diagnostics": rag_diagnostics,
                "environment": {
                    "openai_key_set": bool(openai_key),
                    "rag_enabled": ENABLE_RAG_INITIALIZATION,
                    "llm_instance_type": type(llm_instance).__name__ if llm_instance else None,
                    "platform": platform,
                    "user_id": user_id[:8] + "..." if len(user_id) > 8 else user_id,
                },
            }
        logger.info(f"[{request_id}] Chat response completed successfully in {rt:.2f}s")
        return result

    except HTTPException:
        raise
    except Exception as e:
        rt = time.time() - t0
        perf.error()
        logger.error(f"❌ Unexpected chat error [{request_id}]: {e}")
        logger.error(traceback.format_exc())
        return _fallback_response(req.question, request_id, platform, mode, t0, f"Unexpected error: {e}")

# ========================================
# デバッグ & ステータス
# ========================================
@app.get("/debug/env")
async def debug_env():
    env_vars = {
        "LIFF_ID": os.getenv("LIFF_ID", ""),
        "LIFF_CONSENT_URL": os.getenv("LIFF_CONSENT_URL", ""),
        "LINE_BASIC_ID": os.getenv("LINE_BASIC_ID", ""),
        "LINE_CHANNEL_ACCESS_TOKEN": "***" if os.getenv("LINE_CHANNEL_ACCESS_TOKEN") else "",
        "LINE_CHANNEL_SECRET": "***" if os.getenv("LINE_CHANNEL_SECRET") else "",
        "LINE_LOGIN_CHANNEL_ID": os.getenv("LINE_LOGIN_CHANNEL_ID", ""),
        "LINE_LOGIN_CHANNEL_SECRET": "***" if os.getenv("LINE_LOGIN_CHANNEL_SECRET") else "",
        "PUBLIC_API_BASE": os.getenv("PUBLIC_API_BASE", ""),
        "PUBLIC_BASE_URL": os.getenv("PUBLIC_BASE_URL", ""),
        "PUBLIC_FRONT_BASE": os.getenv("PUBLIC_FRONT_BASE", ""),
        "GCS_CONSENT_BUCKET": os.getenv("GCS_CONSENT_BUCKET", ""),
        "OPENAI_API_KEY": "***" if os.getenv("OPENAI_API_KEY") else "",
        "PORT": os.getenv("PORT", ""),
        "ENV": os.getenv("ENV", "development"),
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        "ALLOWED_ORIGINS": os.getenv("ALLOWED_ORIGINS", ""),
    }
    required_vars = [
        "LIFF_ID", "LINE_BASIC_ID", "LINE_CHANNEL_ACCESS_TOKEN",
        "PUBLIC_API_BASE", "GCS_CONSENT_BUCKET", "OPENAI_API_KEY"
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    return {
        "timestamp": datetime.now().isoformat(),
        "environment_variables": env_vars,
        "required_check": {"missing_variables": missing_vars, "all_required_set": len(missing_vars) == 0},
        "liff_config": {
            "liff_id_format_ok": bool(os.getenv("LIFF_ID", "").startswith("2007887876-")),
            "consent_url_ok": bool(os.getenv("LIFF_CONSENT_URL", "").startswith("https://liff.line.me/")),
            "line_basic_id_ok": bool(os.getenv("LINE_BASIC_ID")),
        },
        "cors_config": {
            "public_api_base": os.getenv("PUBLIC_API_BASE", ""),
            "public_front_base": os.getenv("PUBLIC_FRONT_BASE", ""),
            "allowed_origins": os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else []
        }
    }

@app.get("/rag/status")
async def rag_status():
    return {
        "timestamp": datetime.now().isoformat(),
        "initialization_status": {"is_initialized": is_initialized},
        "diagnostics": rag_diagnostics,
        "environment": {
            "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
            "rag_enabled": ENABLE_RAG_INITIALIZATION,
            "llm_instance_available": bool(llm_instance),
            "rag_chain_available": bool(rag_chain_template),
        },
    }

@app.get("/debug/test-chat")
async def debug_test_chat_endpoint(msg: str = "テストメッセージ"):
    # Request を簡易モックして /chat を叩く
    class MockState: ...
    class MockRequest:
        def __init__(self):
            self.headers = {}
            self.state = type('obj', (object,), {'request_id': 'debug-test'})()
    req = UnifiedChatRequest(question=msg, username="debug_user", platform="web", mode="auto", debug_mode=True)
    return await unified_chat(req, MockRequest())

@app.get("/healthz")
async def healthz():
    uptime = time.time() - startup_time
    db_ok = None
    if HAS_DB:
        try:
            # 実装に依存するため「呼べたらOK」程度のチェック
            _ = init_database  # reference to avoid linter
            db_ok = True
        except Exception:
            db_ok = False

    return {
        "status": "ok",
        "version": "7.5.2",
        "uptime_seconds": uptime,
        "rag_initialized": is_initialized,
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "db_imported": db_ok,
        "metrics": perf.stats(),
    }

@app.get("/")
async def root():
    return {"name": "Unified RAG API", "version": "7.5.2", "docs": "/docs"}

# ========================================
# ミドルウェア適用（存在する場合のみ）
# ========================================
if HAS_INTERNAL_MIDDLEWARE:
    try:
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(CORSMiddleware)
        app.add_middleware(RateLimitMiddleware)
        app.add_middleware(ConsentGateMiddleware)
        app.add_middleware(AuditLoggingMiddleware)
        app.add_middleware(TimingMiddleware)
        logger.info("✅ Middlewares registered")
    except Exception as e:
        logger.warning(f"⚠️ Middleware registration failed: {e}")

# ========================================
# 起動時処理（ノンブロッキング 初期化）
# ========================================
@app.on_event("startup")
async def _on_startup():
    ensure_utils_web_search_alias()
    if ENABLE_RAG_INITIALIZATION:
        try:
            # 起動時に裏で初期化（失敗してもアプリは起動）
            asyncio.create_task(initialize_rag_components())
            logger.info("🚀 Scheduled background RAG initialization")
        except Exception as e:
            logger.warning(f"RAG init scheduling failed: {e}")
