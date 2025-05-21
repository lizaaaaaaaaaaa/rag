import os
from typing import List, Dict, Optional
from datetime import datetime

# --- Firestoreを使うかどうか環境変数で制御 ---
USE_FIRESTORE = os.getenv("USE_FIRESTORE", "true").lower() == "true"

if USE_FIRESTORE:
    from google.cloud import firestore
    firestore_client = firestore.Client()
    collection_name = "chat_logs"

    def save_chat_log(
        user_id: str,
        query: str,
        answer: str,
        sources: List[Dict],
        tags: List[str] = None,
    ):
        doc_ref = firestore_client.collection(collection_name).document()
        doc_ref.set({
            "user_id": user_id,
            "query": query,
            "answer": answer,
            "sources": sources,
            "tags": tags or [],
            "timestamp": datetime.utcnow(),
        })

    def get_chat_logs(
        tag: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> List[Dict]:
        collection_ref = firestore_client.collection(collection_name)
        query_ref = collection_ref

        if tag:
            query_ref = query_ref.where("tags", "array_contains", tag)
        if user_id:
            query_ref = query_ref.where("user_id", "==", user_id)

        docs = query_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        return [doc.to_dict() for doc in docs]

else:
    # --- ローカルモード用：Firestore未使用 ---
    def save_chat_log(
        user_id: str,
        query: str,
        answer: str,
        sources: List[Dict],
        tags: List[str] = None,
    ):
        print("🟠 save_chat_log: ローカルモードのためFirestore未保存")

    def get_chat_logs(
        tag: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> List[Dict]:
        print("🟠 get_chat_logs: ローカルモードのためFirestore未使用")
        return []
