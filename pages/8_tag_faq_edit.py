import streamlit as st
import pandas as pd
import sqlite3

DB_FILE = "chat_logs.db"  # 必要に応じて変更

st.set_page_config(page_title="タグ・FAQ編集", layout="wide")
st.title("🏷️ タグ／FAQナレッジ管理（管理者専用）")

# 🔒 管理者判定（管理者のみ操作できる）
user = st.session_state.get("user", "")
if user != "admin":
    st.warning("管理者のみ編集できます。")
    st.stop()

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# タグ一覧を取得
try:
    tag_df = pd.read_sql_query("SELECT DISTINCT タグ FROM chat_logs WHERE タグ IS NOT NULL AND タグ != ''", conn)
except Exception:
    tag_df = pd.DataFrame(columns=["タグ"])

st.subheader("【タグ管理】")
st.write("現在のタグ一覧：")
st.dataframe(tag_df)

# タグ追加
with st.form(key="add_tag_form"):
    new_tag = st.text_input("新しいタグを追加")
    add_tag_btn = st.form_submit_button("タグを追加")
    if add_tag_btn and new_tag:
        # chat_logsにダミーで追加してタグ登録（本来は別テーブル化が理想）
        cursor.execute(
            "INSERT INTO chat_logs (timestamp, username, role, question, answer, source, タグ, 顧客) VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)",
            (user, "admin", "", "", "", new_tag, "")
        )
        conn.commit()
        st.success(f"タグ「{new_tag}」を追加しました。")
        st.experimental_rerun()

# タグ削除
if not tag_df.empty:
    del_tag = st.selectbox("削除したいタグを選択", tag_df["タグ"])
    if st.button("選択タグを削除"):
        cursor.execute("UPDATE chat_logs SET タグ = NULL WHERE タグ = ?", (del_tag,))
        conn.commit()
        st.success(f"タグ「{del_tag}」を全データから削除しました。")
        st.experimental_rerun()

# --- FAQ管理（仮） ---
st.subheader("【FAQナレッジ管理（サンプル）】")
st.write("ここにFAQ編集UIやFAQテーブル連携を拡張できます。")

# FAQ編集はchat_logsに「質問・回答・タグ」形式で直接追加する or 別テーブル設計もOK
with st.form(key="add_faq_form"):
    faq_q = st.text_area("FAQ質問")
    faq_a = st.text_area("FAQ回答")
    faq_tag = st.text_input("FAQタグ")
    add_faq_btn = st.form_submit_button("FAQを追加")
    if add_faq_btn and faq_q and faq_a:
        cursor.execute(
            "INSERT INTO chat_logs (timestamp, username, role, question, answer, source, タグ, 顧客) VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)",
            (user, "assistant", faq_q, faq_a, "", faq_tag, "")
        )
        conn.commit()
        st.success("FAQを追加しました！")
        st.experimental_rerun()

# FAQ一覧表示（サンプル：role=assistantかつQ/A/タグあり）
faq_df = pd.read_sql_query(
    "SELECT id, question, answer, タグ FROM chat_logs WHERE role = 'assistant' AND question IS NOT NULL AND answer IS NOT NULL", conn
)
st.write("登録済みFAQ一覧：")
st.dataframe(faq_df)

conn.close()
