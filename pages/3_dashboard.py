import streamlit as st
import psycopg2
import pandas as pd
import os

st.set_page_config(page_title="ダッシュボード", layout="wide")
st.title("📊 チャット履歴ダッシュボード（出典付き）")

# 🔒 ログインチェック
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

username = st.session_state["user"]
is_admin = username == "admin"  # 管理者判定

# === DB接続設定（環境変数から取得／なければデフォルト値） ===
db_host = os.environ.get("DB_HOST", "127.0.0.1")
db_port = int(os.environ.get("DB_PORT", "5432"))
db_name = os.environ.get("DB_NAME", "rag_db")
db_user = os.environ.get("DB_USER", "raguser")
db_password = os.environ.get("DB_PASSWORD", "yourpassword")  # 必ず環境変数で本番値を上書きすること

try:
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password
    )
    cursor = conn.cursor()

    # クエリ
    if is_admin:
        st.success("✅ 管理者モード：すべてのユーザーの履歴を表示中")
        cursor.execute("SELECT * FROM chat_logs ORDER BY timestamp DESC")
    else:
        st.info(f"👤 ユーザーモード：{username} さんの履歴のみ表示中")
        cursor.execute("SELECT * FROM chat_logs WHERE username = %s ORDER BY timestamp DESC", (username,))

    rows = cursor.fetchall()
    colnames = [desc[0] for desc in cursor.description]
    conn.close()

    if rows:
        # DataFrame化（DBのカラム名そのまま使う）
        df = pd.DataFrame(rows, columns=colnames)

        # --- タグ・顧客での絞り込みUI追加 ---
        filter_cols = []
        if "タグ" in df.columns:
            tag_list = ["全て"] + sorted([x for x in df["タグ"].unique() if pd.notnull(x)])
            tag_filter = st.selectbox("タグで絞り込み", tag_list, key="tag_filter")
            if tag_filter != "全て":
                df = df[df["タグ"] == tag_filter]
                filter_cols.append(f"タグ: {tag_filter}")

        if "顧客" in df.columns:
            customer_list = ["全て"] + sorted([x for x in df["顧客"].unique() if pd.notnull(x)])
            customer_filter = st.selectbox("顧客で絞り込み", customer_list, key="customer_filter")
            if customer_filter != "全て":
                df = df[df["顧客"] == customer_filter]
                filter_cols.append(f"顧客: {customer_filter}")

        # --- 絞り込み状態の表示 ---
        if filter_cols:
            st.info("絞り込み中: " + " / ".join(filter_cols))

        # --- ページネーションを追加（ここが新要素） ---
        PAGE_SIZE = 20
        total = len(df)
        if total > 0:
            page = st.number_input("ページ番号", 1, max(1, (total // PAGE_SIZE) + (1 if total % PAGE_SIZE else 0)), 1)
            start = (page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            st.dataframe(df.iloc[start:end], use_container_width=True)
            st.caption(f"{start + 1}～{min(end, total)}件目を表示（全{total}件）")
        else:
            st.info("該当データがありません。")

        # --- エクスポート機能 ---
        st.download_button(
            "📥 CSVダウンロード",
            df.to_csv(index=False),
            file_name="chat_logs.csv"
        )
        st.download_button(
            "📥 JSONダウンロード",
            df.to_json(orient="records", force_ascii=False),
            file_name="chat_logs.json"
        )

    else:
        st.info("履歴がまだありません。")

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
