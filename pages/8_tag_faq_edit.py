import streamlit as st
st.set_page_config(page_title="タグ・FAQ編集", page_icon="✏️", layout="wide")

import pandas as pd
import sqlite3

DB_FILE = "chat_logs.db"  # 必要に応じて変更

# === ページタイトル・説明 ===
st.title("✏️ タグ・FAQ編集ページ")
st.write("""
このページでは管理者がタグやFAQナレッジを追加・編集・削除できます。  
（※現在はchat_logsテーブルを直接操作しています。）
""")

# 🔒 管理者判定（管理者のみ操作できる）
user = st.session_state.get("user", "")
if user != "admin":
    st.warning("管理者のみ編集できます。")
    st.stop()

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# タグ一覧を取得
try:
    tag_df = pd.read_sql_query(
        "SELECT DISTINCT タグ FROM chat_logs WHERE タグ IS NOT NULL AND タグ != ''", conn
    )
except Exception:
    tag_df = pd.DataFrame(columns=["タグ"])

st.subheader("🏷️ タグ管理")
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
        st.rerun()   # ← ここを修正

# タグ削除
if not tag_df.empty:
    del_tag = st.selectbox("削除したいタグを選択", tag_df["タグ"])
    if st.button("選択タグを削除"):
        cursor.execute("UPDATE chat_logs SET タグ = NULL WHERE タグ = ?", (del_tag,))
        conn.commit()
        st.success(f"タグ「{del_tag}」を全データから削除しました。")
        st.rerun()   # ← ここも修正

# --- FAQ管理（サンプル） ---
st.subheader("❓ FAQナレッジ管理（サンプル）")
st.write("ここでFAQ（質問・回答・タグ）を追加できます。")

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
        st.rerun()   # ← ここも修正

# FAQ一覧表示（サンプル：role=assistantかつQ/A/タグあり）
faq_df = pd.read_sql_query(
    "SELECT id, question, answer, タグ FROM chat_logs WHERE role = 'assistant' AND question IS NOT NULL AND answer IS NOT NULL", conn
)
st.write("登録済みFAQ一覧：")
st.dataframe(faq_df)

conn.close()
