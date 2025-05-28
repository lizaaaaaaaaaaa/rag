import streamlit as st
st.set_page_config(page_title="チャット履歴グラフ可視化", page_icon="📈", layout="wide")

import pandas as pd
import sqlite3
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

# --- ログインチェック ---
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

# === ページタイトル・説明 ===
st.title("📈 チャット履歴グラフ可視化")
st.write("""
このページでは、チャット履歴をグラフで可視化できます。  
タグ・顧客・期間ごとにフィルタし、日別推移・タグ別・ユーザー×タグのヒートマップを確認できます。
""")

DB_FILE = "chat_logs.db"

# 管理者モード
is_admin = st.checkbox("管理者モード：全履歴対象", value=False)

# --- DB読み込み ---
conn = sqlite3.connect(DB_FILE)
df = pd.read_sql_query("SELECT * FROM chat_logs", conn)
conn.close()

# タイムスタンプ型変換
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df = df[df["timestamp"].notnull()]
df["date"] = df["timestamp"].dt.date

# データがなければストップ
if df.empty:
    st.info("🔍 データが存在しません。チャット履歴を作成してください！")
    st.stop()

# ========== フィルタUI ==========
tag_list = sorted(df["タグ"].dropna().unique()) if "タグ" in df.columns else []
tag_select = st.multiselect("タグで絞り込み", options=tag_list, default=tag_list)

customer_list = sorted(df["顧客"].dropna().unique()) if "顧客" in df.columns else []
customer_select = st.multiselect("顧客で絞り込み", options=customer_list, default=customer_list)

if not df["date"].empty:
    min_date = df["date"].min()
    max_date = df["date"].max()
else:
    min_date = max_date = datetime.today().date()

date_range = st.date_input(
    "期間で絞り込み",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

# ===== ログインユーザー取得 =====
current_user = st.session_state.get("user")
if not is_admin and current_user:
    df = df[df["username"] == current_user]

# ========== フィルタ適用 ==========
filtered = df.copy()
if "タグ" in filtered.columns:
    filtered = filtered[filtered["タグ"].isin(tag_select)]
if "顧客" in filtered.columns:
    filtered = filtered[filtered["顧客"].isin(customer_select)]
filtered = filtered[filtered["date"].notnull()]
filtered = filtered[(filtered["date"] >= date_range[0]) & (filtered["date"] <= date_range[1])]

st.info(f"抽出件数: {len(filtered)} 件")

# ========== エクスポート機能 ==========
st.subheader("📥 抽出結果をエクスポート")
if not filtered.empty:
    # CSV
    csv = filtered.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="📥 CSVでダウンロード",
        data=csv,
        file_name=f"filtered_chat_logs_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv"
    )

    # JSON
    json_str = filtered.to_json(orient="records", force_ascii=False, indent=2)
    st.download_button(
        label="📥 JSONでダウンロード",
        data=json_str,
        file_name=f"filtered_chat_logs_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json"
    )
else:
    st.info("抽出結果が空なのでエクスポートはできません。")

# ========== グラフ表示例（すべて空データ対策入り） ==========

# 日別推移
daily_counts = filtered.groupby("date").size()
st.subheader("📅 日別 質問数の推移（フィルタ適用後）")
if daily_counts.empty:
    st.info("※ データがありません。")
else:
    fig1, ax1 = plt.subplots()
    daily_counts.plot(kind="bar", ax=ax1)
    ax1.set_xlabel("日付")
    ax1.set_ylabel("質問数")
    ax1.set_title("日別 質問数の推移（フィルタ適用）")
    st.pyplot(fig1)

# タグ別
if "タグ" in filtered.columns:
    tag_counts = filtered["タグ"].value_counts()
    st.subheader("🏷️ タグ別 質問数（フィルタ適用後）")
    if tag_counts.empty:
        st.info("※ データがありません。")
    else:
        fig2, ax2 = plt.subplots()
        tag_counts.plot(kind="bar", ax=ax2)
        ax2.set_xlabel("タグ")
        ax2.set_ylabel("質問数")
        ax2.set_title("タグ別 質問数（フィルタ適用）")
        st.pyplot(fig2)

# ユーザー×タグヒートマップ
if "タグ" in filtered.columns:
    st.subheader("🔥 ユーザー×タグ ヒートマップ（フィルタ適用）")
    heatmap = pd.crosstab(filtered["username"], filtered["タグ"])
    st.dataframe(heatmap)
    if heatmap.empty:
        st.info("※ データがありません。")
    else:
        fig3, ax3 = plt.subplots(figsize=(8, 4))
        sns.heatmap(heatmap, annot=True, fmt="d", cmap="Blues", ax=ax3)
        ax3.set_xlabel("タグ")
        ax3.set_ylabel("ユーザー名")
        ax3.set_title("ユーザー×タグ ヒートマップ（フィルタ適用）")
        st.pyplot(fig3)

st.markdown("---")
st.info("※ 「タグ・顧客・期間」フィルタでグラフ・抽出・エクスポートがリアルタイムで変わります！")
