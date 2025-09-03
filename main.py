# main.py - Unified RAG API (Diagnostics Super-Enhanced) [web chat: consentless]
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
except Exception: pass
_enforce_env_minimums()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
import jwt  # PyJWT

from middleware import (
    TimingMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    ConsentGateMiddleware,
    AuditLoggingMiddleware,
)
from database import init_database

ROOT = pathlib.Path(__file__).resolve().parent
for p in [ROOT, ROOT/"services", ROOT/"llm", ROOT/"rag", ROOT/"api", ROOT/"api"/"routers"]:
    s=str(p)
    if s not in sys.path: sys.path.insert(0, s)

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
                    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore
                    if "utils" not in sys.modules: sys.modules["utils"]=types.ModuleType("utils")
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
    description="High-Performance Unified AI Chat API with Robust Import Guards",
    version="7.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

class RobotsNoIndexMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        if os.getenv("ENV","development")!="production":
            resp.headers["X-Robots-Tag"]="noindex"
        return resp

app.add_middleware(RobotsNoIndexMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
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

_include_optional_router("api.routers.legal_pages")
_include_optional_router("api.routers.liff_pages")
_include_optional_router("api.routers.line_login")
_include_optional_router("api.routers.reconsent_tasks")
_include_optional_router("api.routers.financial_api")
_include_optional_router("api.routers.financial_api", attr="router_compat")
_include_optional_router("api.routers.consent_gate")

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
        # LLM（省略：元実装どおり） …
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
                except Exception: pass
            rag_diagnostics["component_status"]["llm_instance"]["loaded"]=bool(llm_instance)
        except Exception as e:
            rag_diagnostics["component_status"]["llm_instance"]["error"]=str(e)
            logger.warning(f"⚠️ LLM load failed (continue without): {e}")

        # Vectorstore + Chain（省略：元実装どおり） …
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
                        if not self.include_sources: return {"result":ans,"source_documents":[]}
                        docs=[{"metadata":{"source":s}} for s in srcs]; return {"result":ans,"source_documents":docs}
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
        logger.error(f"💥 RAG init failed: {e}"); logger.error(traceback.format_exc())

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
            await initialize_rag_components()

        unified_generator=None; last_err=None
        for m in ("api.routers.chat_unified","routers.chat_unified","chat_unified"):
            try:
                mod=importlib.import_module(m)
                unified_generator=getattr(mod,"unified_generator",mod)
                logger.info(f"Using chat module: {m}"); break
            except Exception as e:
                last_err=e
        if unified_generator is None:
            raise ModuleNotFoundError(f"chat_unified not found: {last_err}")

        response = await unified_generator.generate_response(req.question, platform, username, mode)

        rt=time.time()-t0; perf.record(platform, response.get("source",mode), rt)
        result={"answer":response.get("answer",""),"sources":response.get("sources",[]),"status":response.get("status","ok"),
                "performance":{"total_time":rt,"platform":platform,"mode":mode,"source":response.get("source")},
                "system_info":{"version":"7.5.0","rag_status":"initialized" if is_initialized else "skipped"}}
        if req.debug_mode: result["debug_info"]={"perf":perf.stats()}
        return result

    except Exception as e:
        rt=time.time()-t0; perf.error(); err_id=str(uuid4())[:8]
        logger.error(f"❌ Main chat error [{err_id}]: {e}"); logger.error(traceback.format_exc())
        return JSONResponse(status_code=200, content={"answer":f"システムエラーが発生しました。（エラーID: {err_id}）","sources":[],"status":"error",
                                                      "performance":{"total_time":rt,"platform":platform,"mode":mode}})

@app.get("/")
async def root():
    return {"message":"Unified RAG API - Diagnostics Super-Enhanced","version":"7.5.0",
            "rag_initialized":is_initialized,
            "diagnostic_endpoints":{"rag_status":"/debug/rag-status","chat":"/chat","line_webhook":"/line/webhook"},
            "perf":perf.stats()}

@app.get("/healthz")
async def health_check():
    uptime = time.time()-_BOOT_T0
    return {"status":"healthy" if is_initialized else "degraded","uptime":uptime}

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting Unified RAG System (Diagnostics Super-Enhanced)")
    ensure_utils_web_search_alias()
    await init_database()
    if ENABLE_RAG_INITIALIZATION:
        await initialize_rag_components()
    if ENABLE_LINE_INTEGRATION:
        try:
            try: mod = importlib.import_module("api.routers.line_bot_ultra_fast")
            except Exception: mod = importlib.import_module("routers.line_bot_ultra_fast")
            line_router=getattr(mod,"router"); app.include_router(line_router, prefix="", tags=["line"])
            logger.info("✅ LINE router included")
        except Exception as e:
            logger.error(f"ℹ️ LINE router not included: {e}")
    try:
        logger.info(json.dumps({"evt":"boot","phase":"ready","ms":int((time.time()-_BOOT_T0)*1000)}))
    except Exception: pass

if __name__=="__main__":
    import uvicorn
    port=int(os.getenv("PORT","8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
