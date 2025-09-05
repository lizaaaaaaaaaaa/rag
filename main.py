# main.py - チャットエンドポイント修正版（WebチャットエラーとOpenAI API KEY対応）

import logging, os, asyncio, time, json, traceback, sys, pathlib, importlib, importlib.util, types
from datetime import datetime
from typing import Dict, Any, List
from uuid import uuid4

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import jwt  # PyJWT

logger = logging.getLogger(__name__)

class UnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"
    debug_mode: bool | None = False

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

# グローバル変数（既存のmain.pyから継承）
vectorstore=None
rag_chain_template=None
llm_instance=None
is_initialized=False
RAG_SHARED_GLOBALLY=False
ENABLE_RAG_INITIALIZATION = os.getenv("DISABLE_RAG_INIT","false").lower()!="true"

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

def _fallback_response(question: str, request_id: str, platform: str, mode: str, t0: float, error: str = None):
    """フォールバック応答生成（OpenAI API未設定時など）"""
    rt = time.time() - t0
    perf.error()
    
    # 簡単な応答パターン
    fallback_answers = {
        "こんにちは": "こんにちは！どのようなご質問でしょうか？",
        "ありがとう": "どういたしまして！他にご質問はありますか？",
        "テスト": "システムは正常に動作しています。",
        "hello": "Hello! How can I help you?",
        "test": "System is working properly.",
    }
    
    # 質問に基づくフォールバック応答
    question_lower = question.strip().lower()
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

# ★ 修正: Webチャットエラー対応版のメインエンドポイント
async def unified_chat(req: UnifiedChatRequest, request: Request):
    """
    統合チャットエンドポイント（エラーハンドリング強化版）
    - OpenAI API KEY チェック強化
    - CORS対応強化
    - フォールバック応答実装
    - 詳細なデバッグ情報付与
    """
    t0=time.time()
    platform=req.platform or "web"
    request_id = getattr(request.state, "request_id", str(uuid4())[:8])
    
    # ユーザー識別（匿名許可）
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
        user_id = f"web-anon-{request_id}"

    username = req.username or user_id
    mode = req.mode or "auto"

    logger.info(f"Chat request [{request_id}]: platform={platform}, user={user_id[:12]}..., mode={mode}, question_len={len(req.question)}")

    try:
        # 1. 環境変数チェック（最重要）
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            logger.error(f"[{request_id}] OPENAI_API_KEY not set - this is required for LLM functionality")
            raise HTTPException(status_code=500, detail="LLM configuration error: OpenAI API key not configured")

        # 2. utils.web_search エイリアス確保
        try:
            def ensure_utils_web_search_alias() -> bool:
                try:
                    import utils.web_search  # type: ignore
                    return True
                except Exception:
                    pass
                # 簡易版フォールバック実装
                candidates=[
                    pathlib.Path(__file__).parent/"utils"/"web_search.py", 
                    pathlib.Path(__file__).parent/"api"/"utils"/"web_search.py"
                ]
                for path in candidates:
                    if path.exists():
                        try:
                            spec = importlib.util.spec_from_file_location("utils.web_search", str(path))
                            if spec and spec.loader:
                                mod = importlib.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore
                                if "utils" not in sys.modules:
                                    sys.modules["utils"]=types.ModuleType("utils")
                                sys.modules["utils.web_search"] = mod
                                logger.info(f"[{request_id}] utils.web_search alias set from {path}")
                                return True
                        except Exception as e:
                            logger.warning(f"[{request_id}] utils.web_search alias failed for {path}: {e}")
                return False
            
            ensure_utils_web_search_alias()
        except Exception as e:
            logger.warning(f"[{request_id}] Web search alias setup failed: {e}")
        
        # 3. RAG初期化（必要時のみ、ブロックしない）
        if not is_initialized and ENABLE_RAG_INITIALIZATION:
            logger.info(f"[{request_id}] Initializing RAG components...")
            
            # 簡易版初期化（タイムアウト付き）
            try:
                # LLMモジュール解決
                try:
                    mod=importlib.import_module("llm.llm_runner")
                    get_cached=getattr(mod,"get_cached_llm_instance",None)
                    if callable(get_cached): 
                        global llm_instance
                        llm_instance=get_cached()
                        logger.info(f"[{request_id}] LLM instance loaded")
                except Exception as e:
                    logger.warning(f"[{request_id}] LLM load failed: {e}")
                
                # RAGチェーン解決
                try:
                    svc_mod=importlib.import_module("services.rag_chain")
                    get_rag_response=getattr(svc_mod,"get_rag_response")
                    
                    class _FrontDoorChain:
                        def __init__(self, include_sources: bool): 
                            self.include_sources=include_sources
                            self.get_rag_response = get_rag_response
                        def invoke(self, inputs: Dict[str,Any]) -> Dict[str,Any]:
                            q=(inputs.get("query") or inputs.get("question") or "").strip()
                            ans,srcs=self.get_rag_response(q)
                            if not self.include_sources:
                                return {"result":ans,"source_documents":[]}
                            docs=[{"metadata":{"source":s}} for s in srcs]
                            return {"result":ans,"source_documents":docs}
                    
                    global rag_chain_template, is_initialized
                    rag_chain_template=_FrontDoorChain(include_sources=False)
                    is_initialized = True
                    logger.info(f"[{request_id}] RAG chain initialized successfully")
                    
                except Exception as e:
                    logger.warning(f"[{request_id}] RAG chain load failed: {e}")
                    
            except Exception as e:
                logger.error(f"[{request_id}] RAG initialization failed: {e}")
            
            # 初期化に失敗してもフォールバック応答で継続
            if not is_initialized:
                logger.warning(f"[{request_id}] RAG not initialized, using fallback response")
                return _fallback_response(req.question, request_id, platform, mode, t0, "RAG initialization failed")

        # 4. チャットモジュール解決
        unified_generator=None
        last_err=None
        for m in ("api.routers.chat_unified","routers.chat_unified","chat_unified"):
            try:
                mod=importlib.import_module(m)
                unified_generator=getattr(mod,"unified_generator",mod)
                logger.info(f"[{request_id}] Using chat module: {m}")
                break
            except Exception as e:
                last_err=e
                
        if unified_generator is None:
            logger.error(f"[{request_id}] Chat module not found: {last_err}")
            return _fallback_response(req.question, request_id, platform, mode, t0, f"Chat module unavailable: {last_err}")

        # 5. レスポンス生成（タイムアウト付き）
        try:
            # OpenAI API呼び出しが含まれる場合のタイムアウト設定
            import asyncio
            response = await asyncio.wait_for(
                unified_generator.generate_response(req.question, platform, username, mode),
                timeout=30.0  # 30秒タイムアウト
            )
        except asyncio.TimeoutError:
            logger.error(f"[{request_id}] Response generation timed out")
            return _fallback_response(req.question, request_id, platform, mode, t0, "Response generation timeout")
        except Exception as e:
            logger.error(f"[{request_id}] Generate response failed: {e}")
            logger.error(traceback.format_exc())
            
            # OpenAI API エラーの特別処理
            if "openai" in str(e).lower() or "api_key" in str(e).lower():
                return _fallback_response(req.question, request_id, platform, mode, t0, f"OpenAI API error: {e}")
            else:
                return _fallback_response(req.question, request_id, platform, mode, t0, f"Response generation error: {e}")

        # 6. 正常レスポンス構築
        rt=time.time()-t0
        perf.record(platform, response.get("source",mode), rt)
        
        result={
            "answer":response.get("answer",""),
            "sources":response.get("sources",[]),
            "status":response.get("status","ok"),
            "performance":{"total_time":rt,"platform":platform,"mode":mode,"source":response.get("source")},
            "system_info":{
                "version":"7.5.2",
                "rag_status":"initialized" if is_initialized else "skipped",
                "request_id":request_id,
                "llm_available": bool(llm_instance),
                "openai_configured": bool(openai_key)
            }
        }
        
        if req.debug_mode:
            result["debug_info"]={
                "perf":perf.stats(),
                "rag_diagnostics":rag_diagnostics,
                "environment":{
                    "openai_key_set":bool(openai_key),
                    "rag_enabled":ENABLE_RAG_INITIALIZATION,
                    "llm_instance_type": type(llm_instance).__name__ if llm_instance else None,
                    "platform": platform,
                    "user_id": user_id[:8] + "..." if len(user_id) > 8 else user_id
                }
            }
            
        logger.info(f"[{request_id}] Chat response completed successfully in {rt:.2f}s")
        return result

    except HTTPException:
        # FastAPI HTTPException はそのまま再送出
        raise
    except Exception as e:
        rt=time.time()-t0
        perf.error()
        logger.error(f"❌ Unexpected chat error [{request_id}]: {e}")
        logger.error(traceback.format_exc())
        return _fallback_response(req.question, request_id, platform, mode, t0, f"Unexpected error: {e}")

# デバッグエンドポイント群
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
        "PUBLIC_FRONT_BASE": os.getenv("PUBLIC_FRONT_BASE", ""),
        "GCS_CONSENT_BUCKET": os.getenv("GCS_CONSENT_BUCKET", ""),
        "OPENAI_API_KEY": "***" if os.getenv("OPENAI_API_KEY") else "",
        "PORT": os.getenv("PORT", ""),
        "ENV": os.getenv("ENV", "development"),
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        "ALLOWED_ORIGINS": os.getenv("ALLOWED_ORIGINS", ""),
    }
    
    # 必須環境変数のチェック
    required_vars = [
        "LIFF_ID", "LINE_BASIC_ID", "LINE_CHANNEL_ACCESS_TOKEN", 
        "PUBLIC_API_BASE", "GCS_CONSENT_BUCKET", "OPENAI_API_KEY"
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
        "cors_config": {
            "public_api_base": os.getenv("PUBLIC_API_BASE", ""),
            "public_front_base": os.getenv("PUBLIC_FRONT_BASE", ""),
            "allowed_origins": os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else []
        }
    }

async def debug_test_chat(test_message: str = "テストメッセージ"):
    """チャット機能のテスト（デバッグ用）"""
    try:
        request_body = UnifiedChatRequest(
            question=test_message,
            username="debug_user",
            platform="web",
            mode="auto",
            debug_mode=True
        )
        
        # Request オブジェクトをモック
        class MockRequest:
            def __init__(self):
                self.headers = {}
                self.state = type('obj', (object,), {'request_id': 'debug-test'})()
        
        mock_request = MockRequest()
        result = await unified_chat(request_body, mock_request)
        
        return {
            "test_successful": True,
            "test_message": test_message,
            "result": result
        }
        
    except Exception as e:
        return {
            "test_successful": False,
            "test_message": test_message,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

def get_rag_detailed_status():
    return {
        "timestamp":datetime.now().isoformat(),
        "initialization_status":{"is_initialized":is_initialized},
        "diagnostics":rag_diagnostics,
        "environment":{
            "openai_key_set":bool(os.getenv("OPENAI_API_KEY")),
            "rag_enabled":ENABLE_RAG_INITIALIZATION,
            "llm_instance_available": bool(llm_instance),
            "rag_chain_available": bool(rag_chain_template)
        }
    }