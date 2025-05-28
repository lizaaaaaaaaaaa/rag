import streamlit as st
import psycopg2
import pandas as pd
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="ダッシュボード", page_icon="📊", layout="wide")

# 🔒 ログインチェック
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

username = st.session_state["user"]
is_admin = username == "admin"

st.title("📊 チャット履歴ダッシュボード")
st.write("""
ここでは自分のチャット履歴（管理者は全ユーザー分）が確認できます。  
タグや顧客で絞り込みも可能です。エクスポートボタンからCSV/JSON形式でダウンロードもできます。
""")

# === DB接続設定 ===
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "rag_db")
DB_USER = os.environ.get("DB_USER", "raguser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "yourpassword")  # 本番は必ず環境変数を設定！

conn = None
cursor = None

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    cursor = conn.cursor()

    # タグリスト
    cursor.execute("SELECT DISTINCT タグ FROM chat_logs WHERE タグ IS NOT NULL ORDER BY タグ")
    tag_list = [row[0] for row in cursor.fetchall()]
    tag_list_disp = ["全て"] + tag_list

    # 顧客リスト
    cursor.execute("SELECT DISTINCT 顧客 FROM chat_logs WHERE 顧客 IS NOT NULL ORDER BY 顧客")
    customer_list = [row[0] for row in cursor.fetchall()]
    customer_list_disp = ["全て"] + customer_list

    # 期間フィルタ（初期値: 直近30日）
    today = datetime.today().date()
    default_from = today - timedelta(days=30)
    date_from = st.date_input("表示開始日", default_from)
    date_to = st.date_input("表示終了日", today)

    tag_filter = st.selectbox("タグで絞り込み", tag_list_disp)
    customer_filter = st.selectbox("顧客で絞り込み", customer_list_disp)

    # ページネーション
    PAGE_SIZE = 20
    page = st.number_input("ページ番号", 1, step=1)

    # SQL組み立て
    base_sql = "SELECT * FROM chat_logs WHERE timestamp BETWEEN %s AND %s"
    params = [date_from, date_to + timedelta(days=1)]

    if not is_admin:
        base_sql += " AND username = %s"
        params.append(username)
    if tag_filter != "全て":
        base_sql += " AND タグ = %s"
        params.append(tag_filter)
    if customer_filter != "全て":
        base_sql += " AND 顧客 = %s"
        params.append(customer_filter)

    # 件数カウント
    count_sql = "SELECT COUNT(*) FROM (" + base_sql + ") AS sub"
    cursor.execute(count_sql, params)
    total = cursor.fetchone()[0]

    # ページネーション
    base_sql += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
    params += [PAGE_SIZE, (page - 1) * PAGE_SIZE]

    cursor.execute(base_sql, params)
    rows = cursor.fetchall()
    colnames = [desc[0] for desc in cursor.description]

    if rows:
        df = pd.DataFrame(rows, columns=colnames)
        st.dataframe(df, use_container_width=True)
        st.caption(f"{(page-1)*PAGE_SIZE+1}～{min(page*PAGE_SIZE, total)}件目を表示（全{total}件）")

        # エクスポート
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
        st.info("該当データがありません。")

except Exception as e:
    st.error(f"DBエラーまたはアプリエラーが発生しました: {e}")

finally:
    if cursor is not None:
        cursor.close()
    if conn is not None:
        conn.close()
