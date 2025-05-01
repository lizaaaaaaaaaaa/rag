import streamlit as st
import sqlite3
from datetime import datetime
from rag.ingested_text import load_vectorstore, get_rag_chain

st.set_page_config(page_title="RAGチャット", layout="centered")

# 🛠️ 文字エラー対策関数
def clean_text(text):
    return text.encode("utf-8", "replace").decode("utf-8")

# タイトルと説明
st.markdown("""
<div style="text-align: center;">
    <h1 style="font-size: 2.5em;">💬 RAGチャット</h1>
    <p style="font-size: 1.1em;">PDFから内容を引用して回答するローカル/クラウドハイブリッドチャット</p>
</div>
""", unsafe_allow_html=True)

# セッション初期化
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# 入力フォーム
with st.container():
    st.markdown("### 📝 質問入力")
    user_input = st.text_input("アップロードしたPDFの内容を教えて！", key="chat_input")

    if st.button("🚀 質問する") and user_input:
        st.session_state.chat_history.append(("ユーザー", user_input))

        try:
            vectorstore = load_vectorstore()
            rag_chain = get_rag_chain(vectorstore, return_source=True, question=user_input)
            result = rag_chain.invoke({"query": user_input})
            response = result.get("result", "❌ 回答が見つかりませんでした")
            sources = result.get("source_documents", [])
        except Exception as e:
            response = f"エラーが発生しました: {e}"
            sources = []

        safe_response = clean_text(response)
        st.session_state.chat_history.append(("アシスタント", safe_response))

        # 出典整形
        source_info = "; ".join(
            f"{doc.metadata.get('source', '不明')} (p{doc.metadata.get('page', '?')})"
            for doc in sources
        ) if sources else "なし"

        # DB保存
        try:
            conn = sqlite3.connect("chat_logs.db")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    username TEXT,
                    role TEXT,
                    question TEXT,
                    answer TEXT,
                    source TEXT
                )
            """)
            cursor.execute("""
                INSERT INTO chat_logs (timestamp, username, role, question, answer, source)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                st.session_state.get("user", "guest"),
                "user",
                user_input,
                response,
                source_info
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            st.error(f"DB保存に失敗しました: {e}")

# チャット履歴表示
st.markdown("---")
st.markdown("### 💬 チャット履歴")

for role, msg in reversed(st.session_state.chat_history):
    st.markdown(f"""
    <div style='margin-bottom: 10px; padding: 10px; border-radius: 8px; background-color: #f9f9f9; color: #000000;'>
        <strong>{role}:</strong><br>{clean_text(msg)}
    </div>
    """, unsafe_allow_html=True)
