# main.py - Router登録を堅牢化した完全修正版（v7.5.3）
# - 404多発の根因だった「import 失敗でルーター未登録」を解消
# - /line/webhook, /liff/*, /line-login/*, /consent/* 等を確実に登録
# - 既存の高速RAG/フォールバック/監視ロジックは維持
# -----------------------------------------------------------------------------

import logging, os, asyncio, time, json, traceback, sys, pathlib, importlib, importlib.util, types
from datetime import datetime
from typing import Dict, Any
from uuid import uuid4

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import jwt  # PyJWT

# ===== 自作ミドルウェア =====
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

# ===== DB 初期化（存在チェックのみ） =====
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

# ===== ロガー =====
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main")

# ===== FastAPI =====
app = FastAPI(
    title="Unified RAG API - Enhanced",
    description="High-Performance Unified AI Chat API",
    version="7.5.3",
)

# ---------------------------------------------------------------------
# ルーター安全登録（← 追加：404の根本対策）
# ---------------------------------------------------------------------
def include_router_safe(py_path: str, attr: str = "router", prefix: str = "") -> bool:
    """
    例: py_path="api.routers.liff_pages"
    失敗時は "routers.liff_pages" → "liff_pages" の順でフォールバック。
    見つかった時点で app.include_router して True を返す。
    """
    candidates = [py_path]
    if py_path.startswith("api.routers."):
        base = py_path.split(".", 2)[2]        # "liff_pages" 等
        candidates += [f"routers.{base}", base]
    else:
        candidates += [py_path.split(".")[-1]]

    for modname in candidates:
        try:
            mod = importlib.import_module(modname)
            r = getattr(mod, attr)
            app.include_router(r, prefix=prefix)
            logger.info(f"✅ Router included: {modname}")
            return True
        except Exception as e:
            logger.info(f"ℹ️ Router skipped ({modname}): {e}")
    return False

# ---- 必須ルーターを即時登録（順序も維持）----
# 法務・同意UI・ログイン
include_router_safe("api.routers.legal_pages")
include_router_safe("api.routers.liff_pages")         # /liff, /liff/consent など
include_router_safe("api.routers.consent_gate")       # /consent/* 保存/確認API
include_router_safe("api.routers.line_login")         # /line-login/*

# LINE連携（Webhook/メニュー等）
include_router_safe("api.routers.line_bot_ultra_fast")      # /line/webhook（最重要）
include_router_safe("api.routers.line_proxy")                # 管理/一括設定
include_router_safe("api.routers.line_bot_financial_planner")

# 業務API/各種ユーティリティ
include_router_safe("api.routers.financial_api")
include_router_safe("api.routers.google_oauth")
include_router_safe("api.routers.upload")
include_router_safe("api.routers.history")
include_router_safe("api.routers.healthz")
include_router_safe("api.routers.audit_system")
include_router_safe("api.routers.dashboard")
include_router_safe("api.routers.evaluation")
# 重要：chat_unifiedは /chat エンドポイントを内包しない場合があるため、下の /chat 実装をメインに据える

# ---------------------------------------------------------------------
# グローバル（RAG/LLM）
# ---------------------------------------------------------------------
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False
RAG_SHARED_GLOBALLY = False

# 設定
ENABLE_RAG_INITIALIZATION = os.getenv("DISABLE_RAG_INIT", "false").lower() != "true"
INCLUDE_SOURCES = os.getenv("INCLUDE_SOURCES", "false").lower() == "true"
startup_time = time.time()

rag_diagnostics = {
    "initialization_attempts": 0,
    "initialization_success": False,
    "last_initialization_time": None,
    "initialization_duration": 0.0,
    "component_status": {
        "llm_instance": {"loaded": False, "error": None, "load_time": 0.0},
        "vectorstore": {"loaded": False, "error": None, "load_time": 0.0},
        "rag_chain": {"loaded": False, "error": None, "load_time": 0.0},
    },
    "fallback_info": {"used_fallback": False, "fallback_type": None, "fallback_reason": None},
}

def _enforce_env_minimums():
    mins = {"MAX_NEW_TOKENS": "900", "OPENAI_MAX_TOKENS": "900", "LLM_TIMEOUT": "45"}
    bumped = {}
    for k, v in mins.items():
        cur = os.getenv(k)
        if cur is None or (cur.isdigit() and int(cur) < int(v)):
            os.environ[k] = v
            bumped[k] = v
    if bumped:
        logger.warning(f"BootGuard: bumped env minimums -> {bumped}")

def ensure_utils_web_search_alias() -> bool:
    """utils.web_search の import 別名解決（配置差異に対応）"""
    try:
        import utils.web_search  # noqa
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
                    mod = importlib.module_from_spec(spec)          # type: ignore
                    spec.loader.exec_module(mod)                    # type: ignore
                    if "utils" not in sys.modules:
                        sys.modules["utils"] = types.ModuleType("utils")
                    sys.modules["utils.web_search"] = mod
                    logger.info(f"✅ utils.web_search alias set from {path}")
                    return True
            except Exception as e:
                logger.warning(f"utils.web_search alias failed for {path}: {e}")
    logger.warning("⚠️ utils.web_search could not be resolved; some features may error")
    return False

# 起動時の最低値セット
_enforce_env_minimums()

# ---------------------------------------------------------------------
# RAG 初期化
# ---------------------------------------------------------------------
async def initialize_rag_components():
    global vectorstore, rag_chain_template, llm_instance, is_initialized, RAG_SHARED_GLOBALLY, rag_diagnostics

    if is_initialized:
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

            # ---- LLM ----
            try:
                t = time.time()
                llm_instance = None
                try:
                    mod = importlib.import_module("llm.llm_runner")
                except Exception:
                    mod = importlib.import_module("llm_runner")
                get_cached = getattr(mod, "get_cached_llm_instance", None)
                load_llm = getattr(mod, "load_llm", None)
                if callable(get_cached):
                    llm_instance = get_cached()
                elif callable(load_llm):
                    res = load_llm()
                    llm_instance = res[0] if isinstance(res, tuple) else res
                rag_diagnostics["component_status"]["llm_instance"].update(
                    loaded=bool(llm_instance), load_time=time.time() - t
                )
                logger.info("✅ LLM loaded" if llm_instance else "⚠️ LLM not loaded - will fallback")
            except Exception as e:
                rag_diagnostics["component_status"]["llm_instance"]["error"] = str(e)
                logger.warning(f"LLM load failed: {e}")

            # ---- Vectorstore / Chain ----
            try:
                t = time.time()
                try:
                    fr = importlib.import_module("rag.fast_rag_chain")
                    vectorstore = fr.load_super_fast_vectorstore()
                    rag_chain_template = fr.get_super_fast_rag_chain(vectorstore, return_source=INCLUDE_SOURCES)
                    logger.info("✅ Fast RAG chain loaded")
                except Exception as e_fast:
                    logger.warning(f"⚠️ Fast RAG init failed: {e_fast}  -> fallback to services.rag_chain")
                    try:
                        svc = importlib.import_module("services.rag_chain")
                    except ModuleNotFoundError:
                        svc = importlib.import_module("rag_chain")
                    get_rag_response = getattr(svc, "get_rag_response")

                    class _FrontDoorChain:
                        def __init__(self, include_sources: bool):
                            self.include_sources = include_sources
                        def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
                            q = (inputs.get("query") or inputs.get("question") or "").strip()
                            ans, srcs = get_rag_response(q)
                            docs = [] if not self.include_sources else [{"metadata": {"source": s}} for s in srcs]
                            return {"result": ans, "source_documents": docs}

                    vectorstore = None
                    rag_chain_template = _FrontDoorChain(include_sources=INCLUDE_SOURCES)
                    rag_diagnostics["fallback_info"].update({
                        "used_fallback": True,
                        "fallback_type": "services_front_door",
                        "fallback_reason": str(e_fast)
                    })
                    logger.info("✅ Fallback RAG chain loaded")

                dt = time.time() - t
                rag_diagnostics["component_status"]["vectorstore"]["load_time"] = dt
                rag_diagnostics["component_status"]["rag_chain"]["load_time"] = dt
                rag_diagnostics["component_status"]["vectorstore"]["loaded"] = True
                rag_diagnostics["component_status"]["rag_chain"]["loaded"] = True

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

# ---------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------
class UnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"
    debug_mode: bool | None = False

def _fallback_response(question: str, request_id: str, platform: str, mode: str, t0: float, error: str = None):
    rt = time.time() - t0
    fallback = "申し訳ございません。現在システムが一時的に利用できないため、しばらく時間をおいてから再度お試しください。"
    if question and any(k in question for k in ["家", "住宅", "間取り"]):
        fallback = "住まいに関するご質問ですね。現在メンテナンス中のため、詳しい回答は担当者からご案内します。"
    return JSONResponse(status_code=200, content={
        "answer": fallback, "sources": [], "status": "fallback",
        "performance": {"total_time": rt, "platform": platform, "mode": mode},
        "system_info": {"version": "7.5.3", "rag_status": "error" if error else "unavailable",
                        "request_id": request_id, "error": error or "System temporarily unavailable"}
    })

@app.post("/chat")
async def unified_chat(req: UnifiedChatRequest, request: Request):
    t0 = time.time()
    platform = (req.platform or "web").lower()
    request_id = getattr(request.state, "request_id", str(uuid4())[:8])

    try:
        # 1) OpenAI キー確認
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise HTTPException(status_code=500, detail="LLM configuration error: OpenAI API key not configured")

        # 2) web_search 別名
        try:
            ensure_utils_web_search_alias()
        except Exception as e:
            logger.warning(f"[{request_id}] web_search alias failed: {e}")

        # 3) RAG 初期化
        if ENABLE_RAG_INITIALIZATION and not is_initialized:
            await initialize_rag_components()
            if not is_initialized:
                return _fallback_response(req.question, request_id, platform, req.mode or "auto", t0, "RAG initialization failed")

        # 4) chat_unified を解決
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
            return _fallback_response(req.question, request_id, platform, req.mode or "auto", t0, f"Chat module unavailable: {last_err}")

        # 5) 応答生成（タイムアウト制御）
        try:
            resp = await asyncio.wait_for(
                unified_generator.generate_response(req.question, platform, req.username or f"{platform}-user", req.mode or "auto"),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            return _fallback_response(req.question, request_id, platform, req.mode or "auto", t0, "Response generation timeout")
        except Exception as e:
            return _fallback_response(req.question, request_id, platform, req.mode or "auto", t0, f"Response generation error: {e}")

        rt = time.time() - t0
        return {
            "answer": resp.get("answer", ""),
            "sources": resp.get("sources", []),
            "status": resp.get("status", "ok"),
            "performance": {"total_time": rt, "platform": platform, "mode": req.mode or "auto", "source": resp.get("source")},
            "system_info": {"version": "7.5.3", "rag_status": "initialized" if is_initialized else "skipped",
                            "request_id": request_id, "openai_configured": True},
        }

    except HTTPException:
        raise
    except Exception as e:
        return _fallback_response(req.question, request_id, platform, req.mode or "auto", t0, f"Unexpected error: {e}")

# ---------------------------------------------------------------------
# デバッグ/ヘルス
# ---------------------------------------------------------------------
@app.get("/debug/env")
async def debug_env():
    env_vars = {
        "LIFF_ID": os.getenv("LIFF_ID", ""),
        "LIFF_CONSENT_URL": os.getenv("LIFF_CONSENT_URL", ""),
        "LINE_BASIC_ID": os.getenv("LINE_BASIC_ID", ""),
        "PUBLIC_API_BASE": os.getenv("PUBLIC_API_BASE", ""),
        "PUBLIC_FRONT_BASE": os.getenv("PUBLIC_FRONT_BASE", ""),
        "GCS_CONSENT_BUCKET": os.getenv("GCS_CONSENT_BUCKET", os.getenv("GCS_BUCKET_NAME", "")),
        "OPENAI_API_KEY": "***" if os.getenv("OPENAI_API_KEY") else "",
        "ALLOWED_ORIGINS": os.getenv("ALLOWED_ORIGINS", ""),
    }
    required = ["OPENAI_API_KEY", "PUBLIC_API_BASE"]
    missing = [k for k in required if not os.getenv(k)]
    return {
        "timestamp": datetime.now().isoformat(),
        "environment_variables": env_vars,
        "required_check": {"missing_variables": missing, "all_required_set": len(missing) == 0},
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

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "version": "7.5.3",
        "uptime_seconds": time.time() - startup_time,
        "rag_initialized": is_initialized,
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "db_imported": HAS_DB,
    }

@app.get("/")
async def root():
    return {"name": "Unified RAG API", "version": "7.5.3", "docs": "/docs"}

# ---------------------------------------------------------------------
# ミドルウェア適用（★最小差分：Consent を環境変数で切替）
# ---------------------------------------------------------------------
if HAS_INTERNAL_MIDDLEWARE:
    try:
        # 追加: 環境変数でON/OFF（既定: ON）
        CONSENT_MIDDLEWARE = os.getenv("CONSENT_MIDDLEWARE", "true").lower() in ("1", "true", "yes", "on")

        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(CORSMiddleware)
        app.add_middleware(RateLimitMiddleware)
        if CONSENT_MIDDLEWARE:
            app.add_middleware(ConsentGateMiddleware)   # ← /upload は middleware.py 側で除外済み
        app.add_middleware(AuditLoggingMiddleware)
        app.add_middleware(TimingMiddleware)
        logger.info("✅ Middlewares registered (CONSENT_MIDDLEWARE=%s)", CONSENT_MIDDLEWARE)
    except Exception as e:
        logger.warning(f"⚠️ Middleware registration failed: {e}")

# ---------------------------------------------------------------------
# 起動時処理
# ---------------------------------------------------------------------
@app.on_event("startup")
async def _on_startup():
    try:
        ensure_utils_web_search_alias()
        if ENABLE_RAG_INITIALIZATION:
            asyncio.create_task(initialize_rag_components())   # ノンブロッキング
            logger.info("🚀 Scheduled background RAG initialization")
    except Exception as e:
        logger.warning(f"Startup init failed: {e}")
