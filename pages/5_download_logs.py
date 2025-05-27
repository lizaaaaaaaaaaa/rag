import streamlit as st
st.set_page_config(page_title="履歴ダウンロード", page_icon="🗒️", layout="wide")  # ←import直後

import sqlite3
import pandas as pd
from datetime import datetime

DB_FILE = "chat_logs.db"

# 🔒 ログインチェック
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

# === ページタイトル・説明 ===
st.title("🗒️ チャット履歴ダウンロード")
st.write("""
このページでは、自分（または管理者の場合は全ユーザー）のチャット履歴をCSVまたはJSON形式でダウンロードできます。
""")

username = st.session_state["user"]
is_admin = username == "admin"  # 管理者判定

# DB接続
try:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if is_admin:
        st.success("✅ 管理者モード：全ユーザー履歴ダウンロード可能")
        query = "SELECT * FROM chat_logs ORDER BY timestamp DESC"
        cursor.execute(query)
    else:
        st.info(f"👤 ユーザーモード：{username} さんの履歴のみダウンロード可能")
        query = "SELECT * FROM chat_logs WHERE username = ? ORDER BY timestamp DESC"
        cursor.execute(query, (username,))

    rows = cursor.fetchall()
    conn.close()

    # 必要ならカラム名はDBの設計に合わせて修正
    colnames = [desc[0] for desc in cursor.description] if rows else []

    if rows:
        df = pd.DataFrame(rows, columns=colnames)

        # 📄 ファイル名を自動生成
        now_str = datetime.now().strftime("%Y%m%d_%H%M")
        filename_base = f"chat_logs_{username}_{now_str}"

        # CSVダウンロードボタン
        csv = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label="📥 CSVでダウンロード",
            data=csv,
            file_name=f"{filename_base}.csv",
            mime="text/csv"
        )

        # JSONダウンロードボタン
        json_str = df.to_json(orient="records", force_ascii=False, indent=2)
        st.download_button(
            label="📥 JSONでダウンロード",
            data=json_str,
            file_name=f"{filename_base}.json",
            mime="application/json"
        )

    else:
        st.info("履歴データがありません。")

except Exception as e:
    st.error(f"❌ エラーが発生しました: {e}")
