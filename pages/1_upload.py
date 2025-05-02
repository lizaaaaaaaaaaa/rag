import os
import uuid
import streamlit as st
from rag.ingested_text import ingest_pdf_to_vectorstore, load_vectorstore, get_rag_chain

UPLOAD_DIR = "uploaded_docs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

st.set_page_config(page_title="アップロード & RAG質問", layout="wide")
st.title("📤 PDFアップロード & 💬 RAG質問")
st.write("アップロードしたPDFの内容から質問できます")

# ファイルアップロード
uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])

if uploaded_file is not None:
    # 📛 UUIDで保存（日本語ファイル名対応）
    unique_filename = f"{uuid.uuid4().hex}.pdf"
    save_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(save_path, "wb") as f:
        f.write(uploaded_file.read())

    # 空ファイルチェック
    if os.path.getsize(save_path) == 0:
        st.error("❌ アップロードされたPDFが空です。別のファイルを選んでください。")
        st.stop()

    st.success(f"✅ アップロード成功: {unique_filename}")

    try:
        ingest_pdf_to_vectorstore(save_path)
        st.success("✅ ベクトルストア取り込み完了！")
    except Exception as e:
        st.error(f"❌ ベクトル化に失敗しました: {e}")
        st.stop()

    # 質問UI
    st.subheader("💬 質問してみよう！")
    question = st.text_input("アップロードしたPDFの内容について質問")

    if question:
        try:
            vectorstore = load_vectorstore()
            rag_chain = get_rag_chain(vectorstore, return_source=True, question=question)
            result = rag_chain.invoke({"question": question})  # ← 修正！

            st.write(f"📘 回答: {result.get('result', '❌ 回答が見つかりませんでした')}")

            # 出典表示
            if result.get("source_documents"):
                st.write("📎 出典:")
                for doc in result["source_documents"]:
                    source = doc.metadata.get("source", "不明")
                    page = doc.metadata.get("page", "?")
                    st.write(f"- {source} (p{page})")

        except Exception as e:
            st.error(f"❌ RAG応答エラー: {e}")
