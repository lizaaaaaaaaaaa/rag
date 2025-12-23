# rag/ingested_text.py - 完全版（FAQ JSON/JSONL対応・伏字禁止・外部プロンプト化・/tmp優先）

import os
import json
import logging
import sys
import traceback
import re
from pathlib import Path

from langchain_community.document_loaders.pdf import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer
from langchain.schema import Document

# =========================
#  環境・定数
# =========================
GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME", "")
GCS_VEC_DIR = os.environ.get("GCS_VECTORSTORE_PREFIX", "vectorstore")

# 重要：/tmp を既定に（Cloud Run等の書込先）
LOCAL_VECTOR_DIR = os.getenv("VECTOR_DIR", "/tmp/rag/vectorstore")

# ★ここは services/rag_chain.py / rag/fast_rag_chain.py と揃える
#   - 既存: VECTOR_INDEX_NAME
#   - 統一: INDEX_NAME
#   ※互換性のため両方見る（先に INDEX_NAME を優先）
INDEX_NAME = os.getenv("VECTOR_INDEX_NAME") or os.getenv("INDEX_NAME", "index")

# 共通プロンプトのパス（伏字禁止等のルールをここで統一）
PROMPT_PATH = os.getenv("RAG_PROMPT_PATH", "rag/prompt_template.txt")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# 伏字・プレースホルダーの禁止パターン
_PLACEHOLDER_RE = re.compile(
    r"(○○|〇〇|××|X{2,}|XXXX|TBD|未定|要確認|？？？|\?{2,}|＜.*?＞|ここに.*?を書く)"
)

# =========================
#  GCSユーティリティ
# =========================
def _get_gcs_client():
    try:
        from google.cloud import storage
        return storage.Client()
    except Exception as e:
        logger.warning(f"GCS client creation failed: {e}")
        return None

def upload_vectorstore_to_gcs(local_dir: str):
    """ベクトルストアをGCSにアップロード"""
    if not GCS_BUCKET:
        logger.info("GCS_BUCKET_NAME not set, skipping upload")
        return
    try:
        client = _get_gcs_client()
        if not client:
            return
        bucket = client.bucket(GCS_BUCKET)
        for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
            local_path = os.path.join(local_dir, fname)
            if os.path.exists(local_path):
                blob_path = f"{GCS_VEC_DIR}/{fname}"
                blob = bucket.blob(blob_path)
                blob.upload_from_filename(local_path)
                logger.info(f"✅ Uploaded to GCS: gs://{GCS_BUCKET}/{blob_path}")
    except Exception as e:
        logger.error(f"GCS upload error: {e}")

def download_vectorstore_from_gcs(local_dir: str) -> bool:
    """GCSからベクトルストアをダウンロード（存在しない場合はFalse）"""
    if not GCS_BUCKET:
        logger.info("GCS_BUCKET_NAME not set, skipping download")
        return False
    try:
        client = _get_gcs_client()
        if not client:
            return False
        bucket = client.bucket(GCS_BUCKET)
        os.makedirs(local_dir, exist_ok=True)

        downloaded = False
        for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
            blob_path = f"{GCS_VEC_DIR}/{fname}"
            blob = bucket.blob(blob_path)
            local_path = os.path.join(local_dir, fname)
            if blob.exists():
                blob.download_to_filename(local_path)
                logger.info(f"✅ Downloaded from GCS: {blob_path}")
                downloaded = True
        return downloaded
    except Exception as e:
        logger.error(f"GCS download error: {e}")
        return False

# =========================
#  埋め込み
# =========================
# ★方針1（E5 prefix対応）の本体：passage:/query: を付ける
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")

class MyEmbedding(Embeddings):
    """Sentence-Transformers を使う埋め込み（E5 prefix対応）"""
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts):
        texts = [f"passage: {t}" for t in texts]
        return self.model.encode(texts, show_progress_bar=False).tolist()

    def embed_query(self, text):
        text = f"query: {text}"
        return self.model.encode(text).tolist()

# =========================
#  伏字サニタイズ
# =========================
def _strip_placeholders(text: str) -> str:
    if not text:
        return text
    t = _PLACEHOLDER_RE.sub("（資料に記載なし）", text)
    # 置換だらけで極端に短ければ安全文に
    if "（資料に記載なし）" in t and len(t) < 40:
        return "資料から該当箇所を確認できませんでした。必要であれば担当へ確認します。"
    return t

# =========================
#  文章完全性ユーティリティ（既存強化版を踏襲）
# =========================
def ensure_sentence_completeness(text: str, query: str = "") -> str:
    if not text or len(text.strip()) < 5:
        return generate_fallback_response(query)
    text = text.strip()
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        # 端折れパターンの補完（既存ロジック踏襲）
        if text.endswith('や'):
            if "土地" in text:
                text += "建築に関する準備を総合的に進めることをお勧めします。"
            elif "資金" in text:
                text += "住宅ローンの準備を進めることが重要です。"
            else:
                text += "関連する事項についても併せて検討することをお勧めします。"
        elif text.endswith('重要'):
            if "選定" in text:
                text += 'です。詳しい選び方についてはスタッフまでご相談ください。'
            elif "計画" in text:
                text += 'なポイントです。段階的に進めることをお勧めします。'
            else:
                text += 'な要素です。詳細についてはお気軽にお問い合わせください。'
        elif text.endswith('必要'):
            text += 'です。具体的な手続きについてはご相談ください。'
        elif text.endswith('について'):
            text += 'は、詳細をご案内いたします。'
        elif text.endswith('選定') or text.endswith('検討'):
            text += 'も重要な工程です。'
        elif text.endswith('確認') or text.endswith('準備'):
            text += 'を進めることをお勧めします。'
        elif text.endswith('計画') or text.endswith('設計'):
            text += 'が成功の鍵となります。'
        elif text.endswith('性能') or text.endswith('品質'):
            text += 'にこだわっています。'
        elif text.endswith('対応') or text.endswith('仕様'):
            text += 'となっております。'
        elif text.endswith('条件') or text.endswith('基準'):
            text += 'を満たしています。'
        elif text.endswith('など'):
            text += 'があります。詳細はお問い合わせください。'
        elif text.endswith('から'):
            text += '、ご検討ください。'
        elif text.endswith('して'):
            text += 'います。'
        elif text.endswith('また'):
            text += '、詳細についてはお問い合わせください。'
        elif text.endswith('ます') or text.endswith('です') or text.endswith('た') or text.endswith('る'):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif text.endswith('は') or text.endswith('が'):
            text += '重要なポイントです。'
        elif text.endswith('ので') or text.endswith('ため'):
            text += '、詳しくはお気軽にご相談ください。'
        else:
            text += '。' if len(text) > 10 else generate_fallback_response(query)
    return text

def ensure_complete_sentence(text: str) -> str:
    if not text.endswith(('。', '！', '？', '.')):
        if text.endswith('、'):
            text = text[:-1] + '。'
        elif text.endswith(('です', 'ます', 'た', 'る')):
            text += '。'
        elif text.endswith('や'):
            text += '関連する準備を進めることをお勧めします。'
        elif text.endswith('重要'):
            text += 'です。'
        elif text.endswith('必要'):
            text += 'です。'
        else:
            text += '。'
    return text

# =========================
#  Fallback/整形
# =========================
def generate_fallback_response(query: str) -> str:
    if "坪単価" in query or "価格" in query:
        return "坪単価は仕様等により異なります。詳細はお見積りをご案内しますのでお問い合わせください。"
    elif "仕様" in query:
        return "標準仕様や性能の詳細は展示場または担当までお問い合わせください。"
    elif "設備" in query:
        return "設備はご要望に合わせてご提案可能です。詳細はお問い合わせください。"
    elif "土地" in query:
        return "土地探しから建築までトータルでサポートいたします。ご希望条件をお知らせください。"
    elif "ローン" in query or "資金" in query:
        return "住宅ローンや資金計画については専門スタッフがご相談を承ります。"
    else:
        return "参照中の資料から確定情報を見つけられませんでした。必要であれば担当へ確認します。"

def clean_and_format_response(raw_response: str) -> str:
    if not raw_response or len(raw_response.strip()) < 3:
        return "関連する情報が見つかりませんでした。"
    debug_patterns = [
        r"関連文書が見つかりました[:：]?\s*",
        r"関連情報が見つかりました[:：]?\s*",
        r"\d+\.\s*【質問】[^】]*】\s*",
        r"【回答】\s*",
        r"【質問】\s*",
        r"出典[:：]\s*[^\n]*",
        r"/tmp/tmp[a-zA-Z0-9_]*\.pdf",
        r"\([pP]\d+\)",
        r"^\d+\.\s*",
        r"【[^】]*】",
        r"^質問[:：]\s*",
        r"^回答[:：]\s*",
        r"出典[:：][^\n]*",
        r"\.pdf\s*\([pP]\d+\)",
        r"\.pdf\s+\(p\d+\)",
        r"参考文献[:：][^\n]*",
        r"ソース[:：][^\n]*",
        r"情報源[:：][^\n]*",
    ]
    cleaned = raw_response
    for pattern in debug_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

    # 縦書き/短行の寄せ集めを平文に復元（既存ロジック）
    lines = cleaned.split('\n')
    horizontal_content, vertical_buffer = [], []
    for line in lines:
        line = line.strip()
        if not line:
            if vertical_buffer:
                combined = ''.join(vertical_buffer)
                if len(combined) > 5:
                    horizontal_content.append(combined)
                vertical_buffer = []
            continue
        if len(line) <= 2:
            vertical_buffer.append(line)
        else:
            if vertical_buffer:
                combined = ''.join(vertical_buffer)
                if len(combined) > 5:
                    horizontal_content.append(combined)
                vertical_buffer = []
            horizontal_content.append(line)
    if vertical_buffer:
        combined = ''.join(vertical_buffer)
        if len(combined) > 5:
            horizontal_content.append(combined)

    if horizontal_content:
        unique_content = []
        seen_normalized = set()
        for content in horizontal_content:
            if len(content) < 10:
                continue
            normalized = re.sub(r'[。、\s]', '', content.lower())
            is_dup = False
            for seen in seen_normalized:
                similarity = len(set(normalized) & set(seen)) / max(len(set(normalized)), len(set(seen)), 1)
                if similarity > 0.8:
                    is_dup = True
                    break
            if not is_dup:
                seen_normalized.add(normalized)
                unique_content.append(content)
        if unique_content:
            result = max(unique_content, key=lambda x: len(x) + x.count('。') * 10)
        else:
            result = horizontal_content[0] if horizontal_content else ""
    else:
        result = "関連する情報が見つかりませんでした。"

    if result:
        result = re.sub(r'\s+', ' ', result)
        result = re.sub(r'([。！？])\s*', r'\1', result).strip()
        if result and not result.endswith(('。', '！', '？', '.', '!', '?')):
            if result.endswith('、'):
                result = result[:-1] + '。'
            elif result.endswith('や'):
                result += '関連事項についてもご相談ください。'
            elif result.endswith('重要'):
                result += 'です。'
            elif not result.endswith('.'):
                result += '。'
    if not result or len(result) < 15:
        result = "参照中の資料から確定情報を見つけられませんでした。必要であれば担当へ確認します。"
    return result

# =========================
#  ベクトルストア管理
# =========================
def create_initial_vectorstore():
    logger.info("Creating initial vectorstore...")
    embeddings = MyEmbedding(EMBED_MODEL)
    initial_docs = [
        Document(page_content="このシステムはRAGを使用しています。PDFやFAQをアップロードすると、その内容に基づいて回答します。", metadata={"source": "system-init", "page": 1}),
        Document(page_content="アップロード文書はベクトル化され、検索結果を根拠に自然な回答を生成します。", metadata={"source": "system-init", "page": 2}),
    ]
    vectorstore = FAISS.from_documents(initial_docs, embeddings)
    os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
    vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
    upload_vectorstore_to_gcs(LOCAL_VECTOR_DIR)
    logger.info("✅ Initial vectorstore created")
    return vectorstore

def load_vectorstore():
    """ローカル→無ければGCS→それでも無ければ初期化"""
    try:
        _ = download_vectorstore_from_gcs(LOCAL_VECTOR_DIR)
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        if not os.path.exists(index_path):
            logger.info("Vectorstore not found locally, creating initial one...")
            return create_initial_vectorstore()
        embeddings = MyEmbedding(EMBED_MODEL)
        vectorstore = FAISS.load_local(
            LOCAL_VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
        )
        logger.info("✅ Vectorstore loaded successfully")
        return vectorstore
    except Exception as e:
        logger.error(f"Error loading vectorstore: {e}")
        return create_initial_vectorstore()

def ingest_pdf_to_vectorstore(pdf_path: str) -> int:
    """PDFをベクトルストアに追加（メタ補強＋保存＋GCSアップロード）"""
    try:
        loader = PyPDFLoader(pdf_path)
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=100, separators=["\n\n", "\n", "。", "！", "？", "、", " ", ""]
        )
        documents = splitter.split_documents(docs)

        # メタ補強：original_filename / gcs_path / page
        try:
            gcs_bucket = os.getenv("INGEST_GCS_BUCKET") or ""
            gcs_blob   = os.getenv("INGEST_GCS_BLOB_NAME") or ""
            original   = os.getenv("INGEST_ORIGINAL_FILENAME") or os.path.basename(pdf_path)
            gcs_path   = f"gs://{gcs_bucket}/{gcs_blob}" if gcs_bucket and gcs_blob else ""
            for d in documents:
                md = d.metadata or {}
                page = md.get("page") or md.get("page_number") or md.get("pageIndex")
                if page is not None:
                    md["page"] = page
                md.setdefault("original_filename", original)
                if gcs_path:
                    md.setdefault("gcs_path", gcs_path)
                d.metadata = md
        except Exception as _e:
            logger.warning(f"[ingest] metadata enrichment skipped: {_e}")

        embeddings = MyEmbedding(EMBED_MODEL)
        os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        if os.path.exists(index_path):
            vectorstore = FAISS.load_local(
                LOCAL_VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
            )
            vectorstore.add_documents(documents)
        else:
            vectorstore = FAISS.from_documents(documents, embeddings)

        vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
        logger.info(f"✅ Added {len(documents)} documents from {os.path.basename(pdf_path)}")
        upload_vectorstore_to_gcs(LOCAL_VECTOR_DIR)
        return len(documents)
    except Exception as e:
        logger.error(f"Error ingesting PDF: {e}")
        raise

# =========================
#  ★FAQ(JSON/JSONL)のGCS取り込み★
# =========================
def ingest_faq_json_from_gcs(bucket_name: str, prefix: str = "faq/") -> int:
    """
    GCSの JSON/JSONL (質問/回答 or question/answer) を読み込み、FAISSへ追加して保存→GCSへ同期。
    返り値：追加した Document 数
    """
    client = _get_gcs_client()
    if not client:
        logger.error("GCS client unavailable")
        return 0
    _ = client.bucket(bucket_name)

    os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
    emb = MyEmbedding(EMBED_MODEL)
    try:
        vs = FAISS.load_local(LOCAL_VECTOR_DIR, emb, index_name=INDEX_NAME, allow_dangerous_deserialization=True)
    except Exception:
        vs = FAISS.from_texts([""], emb)
        # ダミーの初期1件を除去
        try:
            vs.docstore._dict.pop(next(iter(vs.docstore._dict.keys())), None)
        except Exception:
            pass

    added = 0
    for blob in client.list_blobs(bucket_name, prefix=prefix):
        name = blob.name.lower()
        if not (name.endswith(".jsonl") or name.endswith(".json")):
            continue
        try:
            data = blob.download_as_text(encoding="utf-8")
            items = [json.loads(l) for l in data.splitlines() if l.strip()] if name.endswith(".jsonl") else json.loads(data)
            if not isinstance(items, list):
                logger.warning(f"Skip non-list JSON: gs://{bucket_name}/{blob.name}")
                continue

            docs = []
            for j in items:
                q = j.get("質問") or j.get("question")
                a = j.get("回答") or j.get("answer")
                if not a:
                    continue
                docs.append(Document(
                    page_content=str(a).strip(),
                    metadata={
                        "question": (q or "").strip(),
                        "source": f"gs://{bucket_name}/{blob.name}",
                        "type": "faq"
                    }
                ))
            if docs:
                vs.add_documents(docs)
                added += len(docs)
                logger.info(f"Added {len(docs)} docs from {blob.name}")
        except Exception as e:
            logger.error(f"Failed to ingest {blob.name}: {e}")

    if added:
        vs.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
        upload_vectorstore_to_gcs(LOCAL_VECTOR_DIR)
        logger.info(f"✅ FAQ ingest finished: {added} docs")
    else:
        logger.info("No FAQ docs ingested.")
    return added

# =========================
#  応答生成（自然文）ラッパ
# =========================
def create_natural_response(raw_response: str, query: str) -> str:
    if not raw_response or len(raw_response.strip()) < 3:
        return generate_fallback_response(query)
    cleaned = clean_and_format_response(raw_response)
    # ドメイン別の軽い整形（既存踏襲）
    if "坪単価" in query or "価格" in query or "費用" in query:
        if any(k in cleaned for k in ["坪単価", "万円", "価格", "円"]):
            return f"坪単価についてご案内いたします。{cleaned}仕様や設備によって変動いたしますので、詳細はお問い合わせください。"
        return "坪単価は仕様等で変動します。詳細なお見積りをご案内しますのでお問い合わせください。"
    return ensure_complete_sentence(cleaned)

# =========================
#  RAGチェーン生成
# =========================
def _load_prompt_from_file() -> PromptTemplate:
    """共通テンプレートをファイルから読み込む（無ければ安全な既定値）"""
    if os.path.exists(PROMPT_PATH):
        tpl = open(PROMPT_PATH, encoding="utf-8").read()
    else:
        tpl = (
            "あなたは親切で正確なアシスタントです。以下の【参考情報】だけに基づいて日本語で回答してください。\n"
            "- 伏字やプレースホルダー（例：○○、〇〇、XXXX、TBD、？？？）は絶対に使用しない。\n"
            "- 推測はしない。情報が無い場合は「資料に記載なし」と述べる。\n"
            "- 文章は必ず完結させ、句点（。）で終わる。\n\n"
            "【参考情報】\n{context}\n\n【質問】\n{question}\n\n【回答】"
        )
    return PromptTemplate(input_variables=["context", "question"], template=tpl)

class NaturalResponseChain:
    def __init__(self, base_chain):
        self.base_chain = base_chain
        self.callbacks = []
    def invoke(self, inputs):
        query = inputs.get("query", "")
        try:
            result = self.base_chain.invoke(inputs)
            raw_result = result.get("result", "")
            logger.info(f"Raw RAG result: {raw_result[:150]}...")
            natural_result = create_natural_response(raw_result, query)
            final_complete_result = ensure_sentence_completeness(natural_result, query)
            # ★最終ガード：伏字・プレースホルダー完全除去
            final_complete_result = _strip_placeholders(final_complete_result)
            logger.info(f"Complete natural result: {final_complete_result[:150]}...")
            result["result"] = final_complete_result
            return result
        except Exception as e:
            logger.error(f"Error in natural response generation: {e}")
            logger.error(traceback.format_exc())
            fb = ensure_sentence_completeness(generate_fallback_response(query), query)
            fb = _strip_placeholders(fb)
            return {"result": fb, "source_documents": []}
    def __call__(self, inputs, callbacks=None):
        return self.invoke(inputs)

def get_rag_chain(vectorstore, return_source: bool = True):
    """共通プロンプト読込＋RetrievalQA→自然文整形"""
    logger.info("Creating improved RAG chain...")
    try:
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        prompt = _load_prompt_from_file()
        retriever = vectorstore.as_retriever(search_kwargs={"k": 10})
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        logger.info("✅ Improved RAG chain created successfully")
        return NaturalResponseChain(rag_chain)
    except Exception as e:
        logger.error(f"Error creating improved RAG chain: {e}")
        logger.error(traceback.format_exc())
        return create_fallback_chain(vectorstore)

def create_fallback_chain(vectorstore):
    logger.info("Creating fallback chain...")
    class FallbackChain:
        def __init__(self, vectorstore):
            self.vectorstore = vectorstore
            self.retriever = vectorstore.as_retriever() if vectorstore else None
            self.callbacks = []
        def invoke(self, inputs):
            query = inputs.get("query", "")
            try:
                if not self.retriever:
                    fb = ensure_sentence_completeness(generate_fallback_response(query), query)
                    return {"result": _strip_placeholders(fb), "source_documents": []}
                docs = self.retriever.invoke(query)
                if docs:
                    best = " ".join([d.page_content for d in docs[:2]])
                    try:
                        from llm.llm_runner import load_llm
                        llm, _, _ = load_llm()
                        prompt = (
                            "以下の情報だけを根拠に日本語で自然に回答してください。"
                            "伏字（○○等）禁止・推測禁止・文末は句点。\n\n"
                            f"参考情報: {best[:800]}\n\n質問: {query}\n\n回答："
                        )
                        resp = llm.invoke(prompt)
                        llm_result = resp.content if hasattr(resp, "content") else str(resp)
                        natural = create_natural_response(llm_result, query)
                    except Exception as _e:
                        logger.error(f"LLM fallback error: {_e}")
                        natural = create_natural_response(best, query)
                    final = ensure_sentence_completeness(natural, query)
                    return {"result": _strip_placeholders(final), "source_documents": docs[:3]}
                fb = ensure_sentence_completeness(generate_fallback_response(query), query)
                return {"result": _strip_placeholders(fb), "source_documents": []}
            except Exception as e:
                logger.error(f"Fallback chain error: {e}")
                return {"result": "システムに一時的な問題が発生しています。時間をおいてお試しください。", "source_documents": []}
        def __call__(self, inputs, callbacks=None):
            return self.invoke(inputs)
    return FallbackChain(vectorstore)

# =========================
#  ユーティリティ（健康診断など）
# =========================
def get_openai_api_key():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        logger.error("OPENAI_API_KEY not set!")
    return key

def health_check_vectorstore() -> dict:
    try:
        vectorstore = load_vectorstore()
        test_results = vectorstore.similarity_search("テスト", k=1)
        return {
            "status": "healthy",
            "vectorstore_loaded": True,
            "test_search_results": len(test_results),
            "local_vector_dir": LOCAL_VECTOR_DIR,
            "index_name": INDEX_NAME,
            "sentence_completion_enabled": True
        }
    except Exception as e:
        logger.error(f"Vectorstore health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "vectorstore_loaded": False, "sentence_completion_enabled": True}

def get_vectorstore_info() -> dict:
    try:
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        pkl_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.pkl")
        return {
            "local_vector_dir": LOCAL_VECTOR_DIR,
            "index_name": INDEX_NAME,
            "faiss_file_exists": os.path.exists(index_path),
            "pkl_file_exists": os.path.exists(pkl_path),
            "faiss_file_size": os.path.getsize(index_path) if os.path.exists(index_path) else 0,
            "gcs_bucket": GCS_BUCKET or "Not configured",
            "sentence_completion_enabled": True,
            "completion_patterns": 20
        }
    except Exception as e:
        logger.error(f"Error getting vectorstore info: {e}")
        return {"error": str(e)}

# =========================
#  テスト実行
# =========================
if __name__ == "__main__":
    print("🧪 RAG Ingested Text Test (FAQ JSON/JSONL / Sentence Completion / Placeholder Guard)")
    print("=" * 50)
    info = get_vectorstore_info()
    print("📋 Vectorstore Information:")
    for k, v in info.items():
        print(f"  {k}: {v}")

    print("\n🔍 Health Check:")
    health = health_check_vectorstore()
    for k, v in health.items():
        print(f"  {k}: {v}")

    if health.get("status") == "healthy":
        print("\n💬 Sample RAG Test:")
        try:
            vectorstore = load_vectorstore()
            rag_chain = get_rag_chain(vectorstore)
            for q in ["住宅の標準仕様について教えてください", "家を建てる際の土地探しや", "建築会社の選定が重要"]:
                print(f"\nQuery: {q}")
                resp = rag_chain.invoke({"query": q})
                ans = resp.get("result", "")
                print(f"Response: {ans[:300]}...")
                print(f"Ends with: '{ans[-10:]}'")
        except Exception as e:
            print(f"RAG test error: {e}")
    else:
        print("\n❌ Vectorstore not healthy. Attempting to create initial vectorstore...")
        try:
            _ = create_initial_vectorstore()
            print("✅ Initial vectorstore created successfully!")
        except Exception as e:
            print(f"❌ Failed to create initial vectorstore: {e}")
