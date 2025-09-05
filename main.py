# main.py - Unified RAG API (Diagnostics Super-Enhanced) [web chat: consentless] + Debug Endpoints
import logging, os, asyncio, time, json, traceback, sys, pathlib, importlib, importlib.util, types
from datetime import datetime
from typing import Dict, Any, List
from uuid import uuid4

logger = logging.getLogger(__name__)

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

_BOOT_T0 = time.time()
try:
    logger.info(json.dumps({"evt":"boot","phase":"start"}))
except Exception:
    pass
_enforce_env_minimums()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
import jwt  # PyJWT

# ⬇️ FastAPI標準のCORSは使わず、middleware.py で定義した自前CORSを使用
from middleware import (
    TimingMiddleware,
    CORSMiddleware,               # ★ 自前CORS（liff.line.me 常時許可 + 環境変数から動的許可）
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
    ConsentGateMiddleware,
    AuditLoggingMiddleware,
)

from database import init_database

ROOT = pathlib.Path(__file__).resolve().parent
for p in [ROOT, ROOT/"services", ROOT/"llm", ROOT/"rag", ROOT/"api", ROOT/"api"/"routers"]:
    s=str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

def ensure_utils_web_search_alias() -> bool:
    try:
        import utils.web_search  # type: ignore
        return True
    except Exception:
        pass
    candidates=[ROOT/"utils"/"web_search.py", ROOT/"api"/"utils"/"web_search.py", ROOT/"web_search.py", ROOT/"api"/"routers"/"web_search.py"]
    for path in candidates:
        if path.exists():
            try:
                spec = importlib.util.spec_from_file_location("utils.web_search", str(path))
                if spec and spec.loader:
                    mod = importlib.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore
                    if "utils" not in sys.modules:
                        sys.modules["utils"]=types.ModuleType("utils")
                    sys.modules["utils.web_search"] = mod
                    logging.getLogger(__name__).info(f"✅ utils.web_search alias set from {path}")
                    return True
            except Exception as e:
                logging.getLogger(__name__).warning(f"utils.web_search alias failed for {path}: {e}")
    logging.getLogger(__name__).warning("⚠️ utils.web_search could not be resolved; some features may error")
    return False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Unified RAG API - Diagnostics Super-Enhanced",
    description="High-Performance Unified AI Chat API with Robust Import Guards + Debug Endpoints",
    version="7.5.1",
)

# ── Robots: 非本番は noindex
class RobotsNoIndexMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        if os.getenv("ENV","development")!="production":
            resp.headers["X-Robots-Tag"]="noindex"
        return resp

# ── ミドルウェアの順序が重要！
app.add_middleware(RobotsNoIndexMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(CORSMiddleware)            # ★ 最初にCORS（liff.line.me 等を許可）
app.add_middleware(SecurityHeadersMiddleware) # ★ 次にセキュリティヘッダ（frame-ancestors で LIFF 許可）
app.add_middleware(RateLimitMiddleware)       # ★ /liff/* /consent* はレート制限除外済み
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(ConsentGateMiddleware)

def _include_optional_router(py_path: str, attr: str = "router", prefix: str = "") -> None:
    try:
        mod = importlib.import_module(py_path)
        r = getattr(mod, attr)
        app.include_router(r, prefix=prefix)
        logger.info(f"✅ Router included: {py_path}")
    except Exception as e:
        logger.info(f"ℹ️ Router skipped ({py_path}): {e}")

# 既存構成を尊重しつつ、必要ルーターを先に取り込み
_include_optional_router("api.routers.legal_pages")
_include_optional_router("api.routers.liff_pages")     # ← LIFF 同意ページ（consent.html 不要の内蔵UI）
_include_optional_router("api.routers.line_login")
_include_optional_router("api.routers.reconsent_tasks")
_include_optional_router("api.routers.financial_api")
_include_optional_router("api.routers.financial_api", attr="router_compat")
_include_optional_router("api.routers.consent_gate")
# （必要に応じて）_include_optional_router("api.routers.dashboard")

vectorstore=None
rag_chain_template=None
llm_instance=None
initialization_lock=asyncio.Lock()
is_initialized=False
RAG_SHARED_GLOBALLY=False

ENABLE_RAG_INITIALIZATION = os.getenv("DISABLE_RAG_INIT","false").lower()!="true"
ENABLE_UNIFIED_CHAT=True
ENABLE_LINE_INTEGRATION=True

UNIFIED_CHAT_MODE=os.getenv("UNIFIED_CHAT_MODE","complete")
DEFAULT_PLATFORM="web"
DEFAULT_RESPONSE_MODE="auto"
INCLUDE_SOURCES=os.getenv("INCLUDE_SOURCES","false").lower()=="true"
startup_time=time.time()

rag_diagnostics={
    "initialization_attempts":0,"initialization_success":False,"last_initialization_time":None,"initialization_duration":0.0,
    "component_status":{
        "llm_instance":{"loaded":False,"error":None,"load_time":0.0},
        "vectorstore":{"loaded":False,"error":None,"load_time":0.0,"file_path":None,"file_size":0},
        "rag_chain":{"loaded":False,"error":None,"load_time":0.0},
    },
    "fallback_info":{"used_fallback":False,"fallback_type":None,"fallback_reason":None},
    "health_checks":{"last_check":None,"vectorstore_test":False,"rag_query_test":False,"llm_response_test":False},
}

async def initialize_rag_components():
    global vectorstore, rag_chain_template, llm_instance, is_initialized, RAG_SHARED_GLOBALLY, rag_diagnostics
    if is_initialized:
        logger.info("✅ RAG components already initialized"); return
    async with initialization_lock:
        if is_initialized: return
        t0=time.time()
        rag_diagnostics["initialization_attempts"]+=1
        rag_diagnostics["last_initialization_time"]=datetime.now().isoformat()
        logger.info("🚀 Initializing RAG components (fast first, then services front-door) ...")
    try:
        ensure_utils_web_search_alias()
        # LLM（元実装に準拠）
        try:
            llm_instance=None
            try:
                mod=importlib.import_module("llm.llm_runner")
                get_cached=getattr(mod,"get_cached_llm_instance",None)
                if callable(get_cached): llm_instance=get_cached()
                else:
                    load_llm=getattr(mod,"load_llm",None)
                    if callable(load_llm):
                        res=load_llm(); llm_instance=res[0] if isinstance(res,tuple) else res
            except Exception:
                try:
                    mod=importlib.import_module("llm_runner")
                    get_cached=getattr(mod,"get_cached_llm_instance",None)
                    if callable(get_cached): llm_instance=get_cached()
                except Exception:
                    pass
            rag_diagnostics["component_status"]["llm_instance"]["loaded"]=bool(llm_instance)
        except Exception as e:
            rag_diagnostics["component_status"]["llm_instance"]["error"]=str(e)
            logger.warning(f"⚠️ LLM load failed (continue without): {e}")

        # Vectorstore + Chain（元実装に準拠）
        try:
            try:
                fast_mod=importlib.import_module("rag.fast_rag_chain")
                load_vs=getattr(fast_mod,"load_super_fast_vectorstore")
                get_chain=getattr(fast_mod,"get_super_fast_rag_chain")
                vectorstore=load_vs()
                rag_chain_template=get_chain(vectorstore, return_source=INCLUDE_SOURCES)
                logger.info("✅ Fast RAG chain loaded")
            except Exception as e_fast:
                logger.warning(f"⚠️ Fast RAG init failed: {e_fast}")
                logger.info("🔄 Falling back to services.rag_chain front-door")
                try:
                    svc_mod=importlib.import_module("services.rag_chain")
                except ModuleNotFoundError:
                    svc_mod=importlib.import_module("rag_chain")
                get_rag_response=getattr(svc_mod,"get_rag_response")
                class _FrontDoorChain:
                    def __init__(self, include_sources: bool): self.include_sources=include_sources
                    def invoke(self, inputs: Dict[str,Any]) -> Dict[str,Any]:
                        q=(inputs.get("query") or inputs.get("question") or "").strip()
                        ans,srcs=get_rag_response(q)
                        if not self.include_sources:
                            return {"result":ans,"source_documents":[]}
                        docs=[{"metadata":{"source":s}} for s in srcs]
                        return {"result":ans,"source_documents":docs}
                vectorstore=None
                rag_chain_template=_FrontDoorChain(include_sources=INCLUDE_SOURCES)
                rag_diagnostics["fallback_info"].update({"used_fallback":True,"fallback_type":"services_front_door","fallback_reason":str(e_fast)})
        except Exception as e_vs:
            rag_diagnostics["component_status"]["vectorstore"]["error"]=str(e_vs)
            rag_diagnostics["component_status"]["rag_chain"]["error"]=str(e_vs)
            raise

        is_initialized=True; RAG_SHARED_GLOBALLY=True
        logger.info("🎉 RAG init OK")
    except Exception as e:
        is_initialized=False; RAG_SHARED_GLOBALLY=False
        logger.error(f"💥 RAG init failed: {e}")
        logger.error(traceback.format_exc())

def get_shared_rag_components():
    return {"vectorstore":vectorstore,"rag_chain_template":rag_chain_template,"llm_instance":llm_instance,
            "is_initialized":is_initialized,"shared_globally":RAG_SHARED_GLOBALLY,"diagnostics":rag_diagnostics}

@app.get("/debug/rag-status")
async def get_rag_detailed_status():
    return {"timestamp":datetime.now().isoformat(),"initialization_status":{"is_initialized":is_initialized}}

class PerfMon:
    def __init__(self):
        self.start_time=time.time()
        self.metrics={"chat_requests":0,"web_requests":0,"line_requests":0,"rag_requests":0,"template_requests":0,"total_response_time":0.0,"errors":0}
    def record(self, platform:str, mode:str, rt:float):
        self.metrics["chat_requests"]+=1
        if platform=="line": self.metrics["line_requests"]+=1
        else: self.metrics["web_requests"]+=1
        if mode in ("rag","rag_enhanced"): self.metrics["rag_requests"]+=1
        if mode in ("template","template_enhanced"): self.metrics["template_requests"]+=1
        self.metrics["total_response_time"]+=rt
    def error(self): self.metrics["errors"]+=1
    def stats(self)->Dict[str,Any]:
        total=self.metrics["chat_requests"]; uptime=time.time()-self.start_time
        avg=(self.metrics["total_response_time"]/total) if total else 0
        return {"uptime_seconds":uptime,"total_requests":total,"avg_response_time":avg,**self.metrics}

perf=PerfMon()

class UnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"
    debug_mode: bool | None = False

@app.post("/chat")
@app.post("/chat/")
async def unified_chat(req: UnifiedChatRequest, request: Request):
    t0=time.time()
    platform=req.platform or "web"
    # ★ 匿名許可：X-User-Id が無ければ web-anon
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        auth = request.headers.get("Authorization","")
        if auth.startswith("Bearer "):
            token = auth.split(" ",1)[1]
            try:
                payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256","RS256","ES256"])
                user_id = payload.get("sub") or payload.get("user_id") or payload.get("email")
            except Exception:
                user_id = None
    if not user_id:
        user_id = "web-anon"

    username = req.username or user_id
    mode = req.mode or "auto"

    try:
        ensure_utils_web_search_alias()
        if not is_initialized and ENABLE_RAG_INITIALIZATION:
            # ここは従来通り同期初期化（ユーザーに確実な体験を届けるため）
            await initialize_rag_components()

        unified_generator=None; last_err=None
        for m in ("api.routers.chat_unified","routers.chat_unified","chat_unified"):
            try:
                mod=importlib.import_module(m)
                unified_generator=getattr(mod,"unified_generator",mod)
                logger.info(f"Using chat module: {m}")
                break
            except Exception as e:
                last_err=e
        if unified_generator is None:
            raise ModuleNotFoundError(f"chat_unified not found: {last_err}")

        response = await unified_generator.generate_response(req.question, platform, username, mode)

        rt=time.time()-t0; perf.record(platform, response.get("source",mode), rt)
        result={"answer":response.get("answer",""),"sources":response.get("sources",[]),"status":response.get("status","ok"),
                "performance":{"total_time":rt,"platform":platform,"mode":mode,"source":response.get("source")},
                "system_info":{"version":"7.5.1","rag_status":"initialized" if is_initialized else "skipped"}}
        if req.debug_mode:
            result["debug_info"]={"perf":perf.stats()}
        return result

    except Exception as e:
        rt=time.time()-t0; perf.error(); err_id=str(uuid4())[:8]
        logger.error(f"❌ Main chat error [{err_id}]: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse(status_code=200, content={
            "answer":f"システムエラーが発生しました。（エラーID: {err_id}）",
            "sources":[],
            "status":"error",
            "performance":{"total_time":rt,"platform":platform,"mode":mode}
        })

@app.get("/")
async def root():
    return {"message":"Unified RAG API - Diagnostics Super-Enhanced","version":"7.5.1",
            "rag_initialized":is_initialized,
            "diagnostic_endpoints":{"rag_status":"/debug/rag-status","chat":"/chat","line_webhook":"/line/webhook"},
            "perf":perf.stats()}

@app.get("/healthz")
async def health_check():
    uptime = time.time()-_BOOT_T0
    return {"status":"healthy" if is_initialized else "degraded","uptime":uptime}

# =========================
# デバッグエンドポイント（追加）
# =========================

@app.get("/debug/env-check")
async def debug_env_check():
    """環境変数の設定状況を確認（デバッグ用）"""
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
        "GCS_CONSENT_BUCKET": os.getenv("GCS_CONSENT_BUCKET", ""),
        "PORT": os.getenv("PORT", ""),
        "ENV": os.getenv("ENV", "development"),
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT", ""),
    }
    
    # 必須環境変数のチェック
    required_vars = [
        "LIFF_ID", "LINE_BASIC_ID", "LINE_CHANNEL_ACCESS_TOKEN", 
        "PUBLIC_API_BASE", "GCS_CONSENT_BUCKET"
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    return {
        "timestamp": datetime.now().isoformat(),
        "environment_variables": env_vars,
        "required_check": {
            "missing_variables": missing_vars,
            "all_required_set": len(missing_vars) == 0
        },
        "liff_config": {
            "liff_id_format_ok": bool(os.getenv("LIFF_ID", "").startswith("2007887876-")),
            "consent_url_ok": bool(os.getenv("LIFF_CONSENT_URL", "").startswith("https://liff.line.me/")),
            "line_basic_id_ok": bool(os.getenv("LINE_BASIC_ID")),
        },
        "api_endpoints": {
            "consent_save": f"{os.getenv('PUBLIC_API_BASE', '')}/consent/save",
            "after_consent": f"{os.getenv('PUBLIC_API_BASE', '')}/line/after-consent",
            "liff_page": f"{os.getenv('PUBLIC_API_BASE', '')}/liff",
        }
    }

@app.post("/debug/test-consent-flow")
async def debug_test_consent_flow(test_user_id: str = "test_user_12345"):
    """同意フローのテスト（デバッグ用）"""
    try:
        results = {}
        
        # 1. 同意チェックテスト
        try:
            from api.routers.line_bot_ultra_fast import _has_consent_sync
            consent_status = _has_consent_sync(test_user_id)
            results["consent_check"] = {"success": True, "has_consent": consent_status}
        except Exception as e:
            results["consent_check"] = {"success": False, "error": str(e)}
        
        # 2. 同意URL生成テスト
        try:
            from api.routers.line_bot_ultra_fast import _make_consent_link
            consent_url = _make_consent_link(test_user_id)
            results["consent_url_generation"] = {"success": True, "url": consent_url}
        except Exception as e:
            results["consent_url_generation"] = {"success": False, "error": str(e)}
        
        # 3. セッション管理テスト
        try:
            from api.routers.line_bot_ultra_fast import sessions
            sessions.set_mode(test_user_id, "ai")
            mode = sessions.get_mode(test_user_id)
            results["session_management"] = {"success": True, "mode_set": mode}
        except Exception as e:
            results["session_management"] = {"success": False, "error": str(e)}
        
        # 4. LINEメッセージング準備チェック
        try:
            from api.routers.line_bot_ultra_fast import _ensure_api
            api = _ensure_api()
            results["line_messaging"] = {"success": bool(api), "api_ready": bool(api)}
        except Exception as e:
            results["line_messaging"] = {"success": False, "error": str(e)}
        
        return {
            "timestamp": datetime.now().isoformat(),
            "test_user_id": test_user_id,
            "results": results,
            "overall_status": "OK" if all(r.get("success", False) for r in results.values()) else "ERROR"
        }
        
    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "test_user_id": test_user_id,
            "error": str(e),
            "overall_status": "FAILED"
        }

@app.get("/debug/line-token-check")
async def debug_line_token_check():
    """LINEアクセストークンの有効性チェック"""
    try:
        import httpx
        
        line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
        if not line_token:
            return {"error": "LINE_CHANNEL_ACCESS_TOKEN not set"}
        
        # LINE Messaging API の bot info を取得してトークンの有効性確認
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.line.me/v2/bot/info",
                headers={"Authorization": f"Bearer {line_token}"},
                timeout=10.0
            )
            
            if response.status_code == 200:
                bot_info = response.json()
                return {
                    "token_valid": True,
                    "bot_info": {
                        "user_id": bot_info.get("userId"),
                        "display_name": bot_info.get("displayName"),
                        "premium_id": bot_info.get("premiumId"),
                    }
                }
            else:
                return {
                    "token_valid": False,
                    "status_code": response.status_code,
                    "error": response.text
                }
                
    except Exception as e:
        return {
            "token_valid": False,
            "error": str(e)
        }

@app.get("/debug/gcs-access-check")
async def debug_gcs_access_check():
    """Google Cloud Storageアクセステスト"""
    try:
        from google.cloud import storage
        
        bucket_name = os.getenv("GCS_CONSENT_BUCKET", "")
        if not bucket_name:
            return {"error": "GCS_CONSENT_BUCKET not set"}
        
        # GCS接続テスト
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        
        # バケットの存在確認
        exists = bucket.exists()
        
        result = {
            "bucket_name": bucket_name,
            "bucket_exists": exists,
            "gcs_client_ready": True
        }
        
        if exists:
            # テストファイル作成（権限確認）
            try:
                test_blob = bucket.blob(f"debug-test/{datetime.now().isoformat()}.txt")
                test_blob.upload_from_string("debug test", content_type="text/plain")
                result["write_permission"] = True
                
                # テストファイル削除
                test_blob.delete()
                result["delete_permission"] = True
                
            except Exception as e:
                result["write_permission"] = False
                result["write_error"] = str(e)
        
        return result
        
    except Exception as e:
        return {
            "gcs_client_ready": False,
            "error": str(e)
        }

# =========================
# 非同期プリウォーム（ブロックしない）
# =========================
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting Unified RAG System (Diagnostics Super-Enhanced)")
    ensure_utils_web_search_alias()

    # DB は待って初期化（依存するルーターのため）
    await init_database()

    # RAG 初期化は「ブロックせず」裏で起動
    if ENABLE_RAG_INITIALIZATION:
        asyncio.create_task(initialize_rag_components())
        logger.info("🧊 RAG prewarm task scheduled (non-blocking)")

    # LINE 連携ルーターは即時インクルード（従来どおり）
    if ENABLE_LINE_INTEGRATION:
        try:
            try:
                mod = importlib.import_module("api.routers.line_bot_ultra_fast")
            except Exception:
                mod = importlib.import_module("routers.line_bot_ultra_fast")
            line_router=getattr(mod,"router")
            app.include_router(line_router, prefix="", tags=["line"])
            logger.info("✅ LINE router included")
        except Exception as e:
            logger.error(f"ℹ️ LINE router not included: {e}")

    try:
        logger.info(json.dumps({"evt":"boot","phase":"ready","ms":int((time.time()-_BOOT_T0)*1000)}))
    except Exception:
        pass

if __name__=="__main__":
    import uvicorn
    port=int(os.getenv("PORT","8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)