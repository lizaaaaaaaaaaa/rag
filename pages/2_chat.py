import streamlit as st
st.set_page_config(page_title="AIチャット最適化版", page_icon="🚀", layout="wide")

import requests
import os
import time
from datetime import datetime

# ==============================================================================
# 設定とAPI URL
# ==============================================================================
API_URL = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
if API_URL.endswith("/"):
    API_URL = API_URL.rstrip("/")

# ==============================================================================
# APIコール関数（最適化版）
# ==============================================================================
def post_chat_optimized(user_input, username, route_preference="auto", platform="web"):
    """最適化版チャットAPI呼び出し"""
    payload = {
        "question": user_input, 
        "username": username,
        "platform": platform,
        "route_preference": route_preference
    }

    # 最適化エンドポイント使用
    url = f"{API_URL}/chat/"

    try:
        start_time = time.time()
        response = requests.post(url, json=payload, timeout=30)
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            res = response.json()
            return {
                "result": res.get("answer") or res.get("result"),
                "sources": res.get("sources", []),
                "performance": res.get("performance", {}),
                "response_time": response_time,
                "status": "success"
            }
        else:
            return {
                "result": f"API エラー: {response.status_code} / {response.text}", 
                "sources": [],
                "response_time": response_time,
                "status": "error"
            }
    except Exception as e:
        return {
            "result": f"通信エラー: {e}", 
            "sources": [],
            "response_time": 0,
            "status": "error"
        }

def get_system_status():
    """システム状態取得"""
    try:
        response = requests.get(f"{API_URL}/system-status", timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        st.error(f"システム状態取得エラー: {e}")
        return None

def test_routing(query, platform="web"):
    """ルーティングテスト"""
    try:
        response = requests.get(f"{API_URL}/routing/test/{query}", 
                              params={"platform": platform}, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        return None

# ==============================================================================
# メインUI
# ==============================================================================
# 未ログインガード
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

username = st.session_state["user"]

# ページタイトルとヘッダー
st.title("🚀 AIチャット（最適化版）")
st.markdown("---")

# サイドバー（設定とステータス）
with st.sidebar:
    st.header("⚙️ 設定")
    
    # ルート選択
    route_preference = st.selectbox(
        "処理ルート選択",
        ["auto", "fast", "rag"],
        help="auto: 自動選択, fast: 高速処理, rag: 高品質回答"
    )
    
    # プラットフォーム選択
    platform = st.selectbox(
        "プラットフォーム",
        ["web", "line"],
        help="web: Webサイト用, line: LINE用最適化"
    )
    
    st.markdown("---")
    
    # システム状態表示
    st.header("📊 システム状態")
    
    if st.button("状態更新"):
        system_status = get_system_status()
        if system_status:
            st.session_state["system_status"] = system_status
    
    if "system_status" in st.session_state:
        status = st.session_state["system_status"]
        
        # 最適化機能状態
        opt_features = status.get("optimization_features", {})
        st.write("**最適化機能**")
        st.write(f"- スマートルーティング: {'✅' if opt_features.get('smart_routing') else '❌'}")
        st.write(f"- 高速ルート: {'✅' if opt_features.get('fast_routes') else '❌'}")
        st.write(f"- 文章完全性: {'✅' if opt_features.get('sentence_completion') else '❌'}")
        
        # ルーティング統計
        routing_stats = status.get("routing_performance", {})
        st.write("**ルーティング統計**")
        st.write(f"- 総リクエスト: {routing_stats.get('total_requests', 0)}")
        st.write(f"- 高速ルート: {routing_stats.get('fast_route_percentage', 0):.1f}%")
        st.write(f"- RAGルート: {routing_stats.get('rag_route_percentage', 0):.1f}%")

# メインチャット画面
col1, col2 = st.columns([3, 1])

with col1:
    st.subheader("💬 チャット")
    
    # チャット入力
    user_input = st.text_input(
        "メッセージを入力してください",
        placeholder="例: 坪単価について教えて、標準仕様はどんな感じ？",
        key="chat_input"
    )
    
    # 送信ボタンとオプション
    send_col1, send_col2, send_col3 = st.columns([1, 1, 2])
    
    with send_col1:
        send_button = st.button("🚀 送信", type="primary")
    
    with send_col2:
        test_routing_button = st.button("🧪 ルーティングテスト")
    
    with send_col3:
        if st.button("🔄 統計リセット"):
            try:
                requests.post(f"{API_URL}/routing/reset-stats", timeout=10)
                st.success("統計をリセットしました")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"リセットエラー: {e}")

with col2:
    st.subheader("🎯 ルート予測")
    
    if user_input and test_routing_button:
        routing_test = test_routing(user_input, platform)
        if routing_test:
            st.write(f"**選択ルート**: {routing_test['selected_route']}")
            st.write(f"**クエリ長**: {routing_test['routing_logic']['query_length']}")
            st.write(f"**高速キーワード**: {'✅' if routing_test['routing_logic']['fast_keywords_matched'] else '❌'}")
            st.write(f"**RAGキーワード**: {'✅' if routing_test['routing_logic']['rag_keywords_matched'] else '❌'}")

# チャット処理
if send_button and user_input.strip():
    with st.spinner("AI が回答を生成中..."):
        start_time = time.time()
        
        # API呼び出し（最適化版）
        api_response = post_chat_optimized(
            user_input, username, route_preference, platform
        )
        
        total_time = time.time() - start_time
        
        # 結果処理
        if api_response["status"] == "success":
            ai_response = api_response.get("result") or "応答エラー"
            performance = api_response.get("performance", {})
            
            # チャット履歴に追加
            st.session_state["messages"].append({
                "role": "user", 
                "content": user_input,
                "timestamp": datetime.now()
            })
            st.session_state["messages"].append({
                "role": "assistant", 
                "content": ai_response,
                "timestamp": datetime.now(),
                "performance": performance,
                "api_response_time": api_response["response_time"]
            })
            
            # 成功メッセージ
            st.success(f"✅ 回答完了 ({total_time:.2f}秒)")
            
            # パフォーマンス情報表示
            with st.expander("📊 パフォーマンス詳細"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("選択ルート", performance.get("selected_route", "不明"))
                with col2:
                    st.metric("処理時間", f"{performance.get('total_time', 0):.3f}s")
                with col3:
                    st.metric("文章完全性", "✅" if performance.get("sentence_complete") else "❌")
                
                st.json(performance)
        else:
            st.error(f"❌ エラーが発生しました: {api_response['result']}")

# チャット履歴表示
st.markdown("---")
st.subheader("📜 チャット履歴")

# 履歴表示設定
show_performance = st.checkbox("パフォーマンス情報を表示", value=False)

# メッセージ表示
for i, message in enumerate(reversed(st.session_state["messages"])):
    if message["role"] == "user":
        with st.container():
            col1, col2 = st.columns([1, 4])
            with col1:
                st.markdown("**🧑 ユーザー**")
            with col2:
                st.markdown(f"*{message['timestamp'].strftime('%H:%M:%S')}*")
            st.markdown(f"> {message['content']}")
    
    else:  # assistant
        with st.container():
            col1, col2 = st.columns([1, 4])
            with col1:
                st.markdown("**🤖 AI**")
            with col2:
                timestamp_text = f"*{message['timestamp'].strftime('%H:%M:%S')}*"
                if "performance" in message and show_performance:
                    perf = message["performance"]
                    route = perf.get("selected_route", "不明")
                    time_taken = perf.get("total_time", 0)
                    complete = "✅" if perf.get("sentence_complete") else "❌"
                    timestamp_text += f" | {route}ルート | {time_taken:.2f}s | 完全性{complete}"
                st.markdown(timestamp_text)
            
            st.markdown(f"💬 {message['content']}")
            
            # パフォーマンス詳細（オプション）
            if show_performance and "performance" in message:
                with st.expander(f"パフォーマンス #{len(st.session_state['messages']) - i}"):
                    st.json(message["performance"])
    
    st.markdown("---")

# フッター情報
with st.container():
    st.markdown("### 💡 使用方法")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **高速処理が適用される質問例:**
        - AI相談を開始
        - 資料請求したい
        - 展示場の見学予約
        - こんにちは
        """)
    
    with col2:
        st.markdown("""
        **RAG処理が適用される質問例:**
        - 坪単価について教えて
        - 標準仕様はどんな感じ？
        - 断熱性能について知りたい
        - 補助金制度について
        """)

# API URL デバッグ情報（開発用）
with st.expander("🔧 開発者情報"):
    st.code(f"API URL: {API_URL}")
    st.code(f"現在の設定: route={route_preference}, platform={platform}")
    
    # システムヘルスチェック
    if st.button("ヘルスチェック"):
        try:
            response = requests.get(f"{API_URL}/healthz", timeout=10)
            if response.status_code == 200:
                health_data = response.json()
                st.json(health_data)
            else:
                st.error(f"ヘルスチェック失敗: {response.status_code}")
        except Exception as e:
            st.error(f"ヘルスチェックエラー: {e}")

# 自動更新設定（オプション）
if st.checkbox("自動システム状態更新（30秒間隔）"):
    import time
    if "last_update" not in st.session_state:
        st.session_state["last_update"] = time.time()
    
    current_time = time.time()
    if current_time - st.session_state["last_update"] > 30:
        system_status = get_system_status()
        if system_status:
            st.session_state["system_status"] = system_status
            st.session_state["last_update"] = current_time
            st.experimental_rerun()