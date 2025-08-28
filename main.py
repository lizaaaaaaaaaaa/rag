# main.py - Unified RAG API (Diagnostics Super-Enhanced) [with Boot Guard]

import logging
import os
import asyncio
import time
import json  # [ADD] Boot Guard ログ用
from datetime import datetime
from typing import Dict, Any, List
from uuid import uuid4
import traceback
import sys
import pathlib
import importlib
import importlib.util
import types

# ================================
# Boot Guard: ENV 下限の強制 & ブート計測
# （重い import/初期化の前に実行）
# ================================
logger = logging.getLogger(__name__)

def _enforce_env_minimums():
    mins = {
        "MAX_NEW_TOKENS": "900",
        "OPENAI_MAX_TOKENS": "900",
        "LLM_TIMEOUT": "45",
    }
    bumped = {}
    for k, v in mins.items():
        cur = os.getenv(k)
        if cur is None or (cur.isdigit() and int(cur) < int(v)):
            os.environ[k] = v
            bumped[k] = v
    if bumped:
        # 起動時に一度だけ警告を出しておく（ログ監視で検知可）
        logger.warning(f"BootGuard: bumped env minimums -> {bumped}")

_BOOT_T0 = time.time()
# Boot開始ログ（Log-based Metricで監視しやすいようJSONに）
try:
    logger.info(json.dumps({"evt": "boot", "phase": "start"}))
except Exception:
    pass
_enforce_env_minimums()
# ===== /Boot Guard =====

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

# =================================
# パス（ローカル/Cloud Run での import 安定化）
# =================================
ROOT = pathlib.Path(__file__).resolve().parent
for p in [ROOT, ROOT / "services", ROOT / "llm", ROOT / "rag", ROOT / "api", ROOT / "api" / "routers"]:
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

# -------------------------------
# “utils.web_search” を強制的に生やす（存在しない環境を吸収）
# -------------------------------
def ensure_utils_web_search_alias() -> bool:
    """
    プロジェクト直下に web_search.py だけがある/パッケージが無い場合でも
    `from utils.web_search import ...` が通るように別名登録する。
    戻り値: 何かしらの方法で alias/読み込みに成功したら True
    """
    try:
        import utils.web_search  # type: ignore
        return True
    except Exception:
        pass

    candidates = [
        ROOT / "utils" / "web_search.py",
        ROOT / "api" / "utils" / "web_search.py",
        ROOT / "web_search.py",
        ROOT / "api" / "routers" / "web_search.py",
    ]
    for path in candidates:
        if path.exists():
            try:
                spec = importlib.util.spec_from_file_location("utils.web_search", str(path))
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)  # type: ignore
                    if "utils" not in sys.modules:
                        sys.modules["utils"] = types.ModuleType("utils")
                    sys.modules["utils.web_search"] = mod
                    logging.getLogger(__name__).info(f"✅ utils.web_search alias set from {path}")
                    return True
            except Exception as e:
                logging.getLogger(__name__).warning(f"utils.web_search alias failed for {path}: {e}")
    logging.getLogger(__name__).warning("⚠️ utils.web_search could not be resolved; some features may error")
    return False

# =================================
# 基本ログ
# =================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =================================
# FastAPI
# =================================
app = FastAPI(
    title="Unified RAG API - Diagnostics Super-Enhanced",
    description="High-Performance Unified AI Chat API with Robust Import Guards",
    version="7.4.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =================================
# noindex ミドルウェア（本番以外）
# =================================
class RobotsNoIndexMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        if os.getenv("ENV", "development") != "production":
            resp.headers["X-Robots-Tag"] = "noindex"
        return resp

app.add_middleware(RobotsNoIndexMiddleware)

# =================================
# ルーター登録（存在する場合のみ）
# =================================
def _include_optional_router(py_path: str, attr: str = "router", prefix: str = "") -> None:
    try:
        mod = importlib.import_module(py_path)
        r = getattr(mod, attr)
        app.include_router(r, prefix=prefix)
        logger.info(f"✅ Router included: {py_path}")
    except Exception as e:
        logger.info(f"ℹ️ Router skipped ({py_path}): {e}")

_include_optional_router("api.routers.legal_pages")
_include_optional_router("api.routers.liff_pages")
_include_optional_router("api.routers.reconsent_tasks")
_include_optional_router("api.routers.financial_api")  # 資金計画のAPIを公開
_include_optional_router("api.routers.financial_api", attr="router_compat")  # [ADD] 旧クライアント互換 (/api/financial-calculate)

# =================================
# グローバル（RAG）
# =================================
vectorstore = None
rag_chain_template = None  # .invoke({"query": ...}) を持つ想定
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False
RAG_SHARED_GLOBALLY = False

# 便利フラグ（環境変数で制御）
ENABLE_RAG_INITIALIZATION = os.getenv("DISABLE_RAG_INIT", "false").lower() != "true"
ENABLE_UNIFIED_CHAT = True
ENABLE_LINE_INTEGRATION = True

UNIFIED_CHAT_MODE = os.getenv("UNIFIED_CHAT_MODE", "complete")
DEFAULT_PLATFORM = "web"
DEFAULT_RESPONSE_MODE = "auto"

INCLUDE_SOURCES = os.getenv("INCLUDE_SOURCES", "false").lower() == "true"
startup_time = time.time()

# 診断情報
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

# =================================
# RAG 初期化（fast 優先 → services にフォールバック）
# =================================
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
        logger.info("🚀 Initializing RAG components (fast first, then services front-door) ...")

        try:
            # ---- STEP 0: import guards ----
            ensure_utils_web_search_alias()

            # ---- STEP 1: LLM ----
            llm_t = time.time()
            try:
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
                rag_diagnostics["component_status"]["llm_instance"]["load_time"] = time.time() - llm_t
                if llm_instance:
                    logger.info(f"✅ LLM ready ({rag_diagnostics['component_status']['llm_instance']['load_time']:.2f}s)")
                else:
                    logger.info("ℹ️ LLM runner not found. Using chain-side LLMs.")
            except Exception as e:
                rag_diagnostics["component_status"]["llm_instance"]["error"] = str(e)
                logger.warning(f"⚠️ LLM load failed (continue without): {e}")

            # ---- STEP 2: Vectorstore + Chain ----
            vs_t = time.time()
            try:
                try:
                    fast_mod = importlib.import_module("rag.fast_rag_chain")
                    load_vs = getattr(fast_mod, "load_super_fast_vectorstore")
                    get_chain = getattr(fast_mod, "get_super_fast_rag_chain")
                    vectorstore = load_vs()
                    rag_chain_template = get_chain(vectorstore, return_source=INCLUDE_SOURCES)
                    logger.info("✅ Fast RAG chain loaded")
                except Exception as e_fast:
                    logger.warning(f"⚠️ Fast RAG init failed: {e_fast}")
                    logger.info("🔄 Falling back to services.rag_chain front-door")

                    svc_mod = importlib.import_module("services.rag_chain")
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
                    rag_diagnostics["fallback_info"].update(
                        {"used_fallback": True, "fallback_type": "services_front_door", "fallback_reason": str(e_fast)}
                    )

                try:
                    _ = rag_chain_template.invoke({"query": "テスト"})
                    rag_diagnostics["health_checks"]["rag_query_test"] = True
                except Exception as test_e:
                    logger.warning(f"⚠️ RAG quick test failed: {test_e}")

                if vectorstore is not None:
                    idx_path = os.path.join(os.getenv("VECTOR_DIR", "rag/vectorstore"), "index.faiss")
                    if os.path.exists(idx_path):
                        rag_diagnostics["component_status"]["vectorstore"]["file_path"] = idx_path
                        rag_diagnostics["component_status"]["vectorstore"]["file_size"] = os.path.getsize(idx_path)
                    rag_diagnostics["component_status"]["vectorstore"]["loaded"] = True

                rag_diagnostics["component_status"]["vectorstore"]["load_time"] = time.time() - vs_t
                rag_diagnostics["component_status"]["rag_chain"]["loaded"] = rag_chain_template is not None
                rag_diagnostics["component_status"]["rag_chain"]["load_time"] = time.time() - vs_t

            except Exception as e_vs:
                rag_diagnostics["component_status"]["vectorstore"]["error"] = str(e_vs)
                rag_diagnostics["component_status"]["rag_chain"]["error"] = str(e_vs)
                raise

            try:
                if hasattr(llm_instance, "invoke"):
                    _r = llm_instance.invoke("テスト")
                    rag_diagnostics["health_checks"]["llm_response_test"] = bool(_r)
            except Exception as e:
                logger.warning(f"LLM test failed: {e}")

            is_initialized = True
            RAG_SHARED_GLOBALLY = True
            rag_diagnostics["initialization_success"] = True
            rag_diagnostics["initialization_duration"] = time.time() - t0
            rag_diagnostics["health_checks"]["last_check"] = datetime.now().isoformat()

            logger.info(
                f"🎉 RAG init OK in {rag_diagnostics['initialization_duration']:.2f}s "
                f"(fallback={rag_diagnostics['fallback_info']['fallback_type']})"
            )

        except Exception as e:
            rag_diagnostics["initialization_success"] = False
            rag_diagnostics["initialization_duration"] = time.time() - t0
            is_initialized = False
            RAG_SHARED_GLOBALLY = False
            logger.error(f"💥 RAG init failed: {e}")
            logger.error(traceback.format_exc())

def get_shared_rag_components():
    return {
        "vectorstore": vectorstore,
        "rag_chain_template": rag_chain_template,
        "llm_instance": llm_instance,
        "is_initialized": is_initialized,
        "shared_globally": RAG_SHARED_GLOBALLY,
        "diagnostics": rag_diagnostics,
    }

# =================================
# 診断系 API
# =================================
from fastapi import APIRouter  # 追加 import はこの位置でもOK

@app.get("/debug/rag-status")
async def get_rag_detailed_status():
    live_health = {
        "vectorstore_accessible": vectorstore is not None,
        "rag_chain_accessible": rag_chain_template is not None,
        "llm_accessible": llm_instance is not None,
        "can_process_query": False,
    }
    if rag_chain_template:
        try:
            quick = rag_chain_template.invoke({"query": "健全性テスト"})
            live_health["can_process_query"] = bool(quick and quick.get("result"))
        except Exception as e:
            live_health["test_error"] = str(e)

    return {
        "timestamp": datetime.now().isoformat(),
        "initialization_status": {
            "is_initialized": is_initialized,
            "globally_shared": RAG_SHARED_GLOBALLY,
            "attempts": rag_diagnostics["initialization_attempts"],
            "success": rag_diagnostics["initialization_success"],
            "last_attempt": rag_diagnostics["last_initialization_time"],
            "duration": rag_diagnostics["initialization_duration"],
        },
        "component_details": rag_diagnostics["component_status"],
        "fallback_info": rag_diagnostics["fallback_info"],
        "health_checks": rag_diagnostics["health_checks"],
    }

@app.post("/debug/fix-rag")
async def attempt_rag_auto_fix():
    global is_initialized, RAG_SHARED_GLOBALLY
    t0 = time.time()
    log: List[str] = []
    try:
        ensure_utils_web_search_alias()
        if is_initialized and rag_chain_template:
            log.append("✅ Components look healthy. Running smoke queries...")
            for q in ["住宅", "坪単価", "標準仕様"]:
                try:
                    r = rag_chain_template.invoke({"query": q})
                    ok = bool(r and r.get("result"))
                    log.append(f" - {q}: {'OK' if ok else 'EMPTY'}")
                except Exception as e:
                    log.append(f" - {q}: ERROR {e}")
        else:
            log.append("❌ Not initialized. Re-initializing ...")
            is_initialized = False
            RAG_SHARED_GLOBALLY = False
            await initialize_rag_components()
            log.append(" - reinit: " + ("OK" if is_initialized else "FAILED"))

        return {
            "fix_attempted": True,
            "fix_duration": time.time() - t0,
            "fix_log": log,
            "final_status": {
                "is_initialized": is_initialized,
                "globally_shared": RAG_SHARED_GLOBALLY,
                "components_ready": {
                    "vectorstore": vectorstore is not None,
                    "rag_chain": rag_chain_template is not None,
                    "llm": llm_instance is not None,
                },
            },
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "fix_attempted": True,
            "fix_successful": False,
            "fix_duration": time.time() - t0,
            "fix_log": log + [f"💥 Auto-fix failed: {e}"],
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }

@app.get("/system-status")
async def system_status():
    return {
        "status": "ok" if is_initialized else "degraded",
        "version": "7.4.0",
        "components": {
            "rag_chain": rag_chain_template is not None,
            "vectorstore": vectorstore is not None,
            "llm": llm_instance is not None,
        },
        "diag": {
            "attempts": rag_diagnostics["initialization_attempts"],
            "success": rag_diagnostics["initialization_success"],
            "duration": rag_diagnostics["initialization_duration"],
        }
    }

# =================================
# パフォーマンスモニタ（簡略）
# =================================
class PerfMon:
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {
            "chat_requests": 0,
            "web_requests": 0,
            "line_requests": 0,
            "rag_requests": 0,
            "template_requests": 0,
            "total_response_time": 0.0,
            "errors": 0,
        }

    def record(self, platform: str, mode: str, rt: float):
        self.metrics["chat_requests"] += 1
        if platform == "line":
            self.metrics["line_requests"] += 1
        else:
            self.metrics["web_requests"] += 1
        if mode in ("rag", "rag_enhanced"):
            self.metrics["rag_requests"] += 1
        if mode in ("template", "template_enhanced"):
            self.metrics["template_requests"] += 1
        self.metrics["total_response_time"] += rt

    def error(self):
        self.metrics["errors"] += 1

    def stats(self) -> Dict[str, Any]:
        total = self.metrics["chat_requests"]
        uptime = time.time() - self.start_time
        avg = (self.metrics["total_response_time"] / total) if total else 0
        return {
            "uptime_seconds": uptime,
            "total_requests": total,
            "avg_response_time": avg,
            "web": self.metrics["web_requests"],
            "line": self.metrics["line_requests"],
            "rag": self.metrics["rag_requests"],
            "template": self.metrics["template_requests"],
            "errors": self.metrics["errors"],
        }

perf = PerfMon()

# =================================
# リクエストモデル
# =================================
class UnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"
    debug_mode: bool | None = False

# =================================
# メインチャット
# =================================
@app.post("/chat")
@app.post("/chat/")
async def unified_chat(req: UnifiedChatRequest, request: Request):
    t0 = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    mode = req.mode or "auto"

    try:
        # 事前に alias を必ず張る（chat_unified 内の `from utils.web_search ...` 対策）
        ensure_utils_web_search_alias()

        if not is_initialized and ENABLE_RAG_INITIALIZATION:
            await initialize_rag_components()

        # chat_unified の場所が repo により変わるので動的 import
        unified_generator = None
        last_err = None
        for m in ("api.routers.chat_unified", "routers.chat_unified", "chat_unified"):
            try:
                mod = importlib.import_module(m)
                unified_generator = getattr(mod, "unified_generator", mod)
                logger.info(f"Using chat module: {m}")
                break
            except Exception as e:
                last_err = e

        if unified_generator is None:
            raise ModuleNotFoundError(f"chat_unified not found: {last_err}")

        # 統一の generate_response を想定
        response = await unified_generator.generate_response(req.question, platform, username, mode)

        rt = time.time() - t0
        perf.record(platform, response.get("source", mode), rt)

        result = {
            "answer": response.get("answer", ""),
            "sources": response.get("sources", []),
            "status": response.get("status", "ok"),
            "performance": {"total_time": rt, "platform": platform, "mode": mode, "source": response.get("source")},
            "system_info": {"version": "7.4.0", "rag_status": "initialized" if is_initialized else "skipped"},
        }
        if req.debug_mode:
            result["debug_info"] = {"rag_diagnostics": rag_diagnostics, "perf": perf.stats()}
        return result

    except Exception as e:
        rt = time.time() - t0
        perf.error()
        err_id = str(uuid4())[:8]
        logger.error(f"❌ Main chat error [{err_id}]: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=200,
            content={
                "answer": f"システムエラーが発生しました。（エラーID: {err_id}）",
                "sources": [],
                "status": "error",
                "performance": {"total_time": rt, "platform": platform, "mode": mode},
            },
        )

# =================================
# ルート/ヘルス
# =================================
@app.get("/")
async def root():
    return {
        "message": "Unified RAG API - Diagnostics Super-Enhanced",
        "version": "7.4.0",
        "rag_initialized": is_initialized,
        "diagnostic_endpoints": {
            "rag_status": "/debug/rag-status",
            "fix_rag": "/debug/fix-rag",
            "system_status": "/system-status",
            "chat": "/chat",
            "line_webhook": "/line/webhook",
        },
        "perf": perf.stats(),
    }

@app.get("/healthz")
async def health_check():
    uptime = time.time() - startup_time
    quick = False
    if rag_chain_template:
        try:
            r = rag_chain_template.invoke({"query": "ヘルスチェック"})
            quick = bool(r and r.get("result"))
        except Exception:
            quick = False
    return {"status": "healthy" if is_initialized else "degraded", "uptime": uptime, "rag_quick_test": quick}

# =================================
# 起動時処理
# =================================
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting Unified RAG System (Diagnostics Super-Enhanced)")

    # 先に alias を張っておく（LINE / web 共通の import 安定化）
    ensure_utils_web_search_alias()

    if ENABLE_RAG_INITIALIZATION:
        await initialize_rag_components()

    # LINE ルーター（存在すれば取り込む）
    if ENABLE_LINE_INTEGRATION:
        try:
            try:
                mod = importlib.import_module("api.routers.line_bot_ultra_fast")
            except Exception:
                mod = importlib.import_module("routers.line_bot_ultra_fast")
            line_router = getattr(mod, "router")
            app.include_router(line_router, prefix="", tags=["line"])
            logger.info("✅ LINE router included")
        except Exception as e:
            logger.error(f"ℹ️ LINE router not included: {e}")

    # Boot 完了ログ（所要ms）
    try:
        logger.info(json.dumps({"evt": "boot", "phase": "ready", "ms": int((time.time() - _BOOT_T0) * 1000)}))
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
