'use client';

import { useEffect, useState } from "react";

// 出典データ型
type Source = {
  metadata: {
    source: string;
    page: string;
    [key: string]: unknown;
  };
};

type ChatHistory = {
  id: string;
  question: string;
  answer: string;
  timestamp: string;
  sources?: Source[];
};

export default function ChatPage() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [history, setHistory] = useState<ChatHistory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 履歴取得
  const fetchHistory = async () => {
    try {
      const res = await fetch("https://rag-api-190389115361.asia-northeast1.run.app/chat/history", {
        credentials: "include",  // ★GETは /chat/history
      });
      if (!res.ok) throw new Error(`API Error: ${res.status}`);
      const data = await res.json();
      setHistory(Array.isArray(data.logs) ? data.logs : []);
    } catch {
      setError("履歴の取得に失敗しました");
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  // チャット送信
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setAnswer(null);
    setSources([]);
    setError(null);
    try {
      const res = await fetch("https://rag-api-190389115361.asia-northeast1.run.app/chat", {
        method: "POST", // ← ここが重要！（/chatにPOST）
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        credentials: "include",
      });
      const data = await res.json();
      setAnswer(data.answer);
      setSources(data.sources || []);
      fetchHistory();
    } catch {
      setError("送信またはAI応答に失敗しました");
    }
    setLoading(false);
    setQuestion("");
  };

  return (
    <div className="simple-container">
      <div className="simple-flex">
        {/* 履歴リスト */}
        <div style={{ flex: 1 }}>
          <div className="simple-box">
            <div className="simple-title">履歴</div>
            {error && <div style={{ color: "red" }}>{error}</div>}
            {(!history || history.length === 0) && <div>履歴がありません</div>}
            {history.map(item => (
              <div key={item.id} style={{
                borderBottom: "1px solid #eee",
                paddingBottom: "0.5rem",
                marginBottom: "0.7rem"
              }}>
                <div><strong>質問：</strong>{item.question}</div>
                <div><strong>回答：</strong>{item.answer}</div>
                <div style={{ fontSize: "0.95em" }}><small>{item.timestamp}</small></div>
                {item.sources && item.sources.length > 0 && (
                  <div style={{ marginTop: "0.3rem", fontSize: "0.9em", color: "#666" }}>
                    <strong>出典：</strong>
                    <ul>
                      {item.sources.map((src, i) => (
                        <li key={i}>
                          <a
                            href={`https://rag-api-190389115361.asia-northeast1.run.app/pdfs/${encodeURIComponent(src.metadata.source)}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: "#1976d2", textDecoration: "underline" }}
                            title={`PDFを開く: ${src.metadata.source}`}
                          >
                            {src.metadata.source}
                          </a>
                          （p.{src.metadata.page}）
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        {/* チャットエリア */}
        <div style={{ flex: 2 }}>
          <div className="simple-box">
            <div className="simple-title">AIチャット</div>
            <form onSubmit={handleSubmit} style={{ marginBottom: "1rem" }}>
              <input
                className="simple-input"
                value={question}
                onChange={e => setQuestion(e.target.value)}
                placeholder="質問を入力してください"
                required
              />
              <button
                className="simple-button"
                type="submit"
                disabled={loading || question === ""}
              >
                {loading ? "送信中..." : "送信"}
              </button>
            </form>
            {answer && (
              <div style={{
                border: "1px solid #333",
                borderRadius: "8px",
                padding: "1rem",
                marginBottom: "1rem",
                background: "#f7faff"
              }}>
                <strong>AIの回答：</strong>
                <div>{answer}</div>
                {/* 最新回答の出典 */}
                {sources.length > 0 && (
                  <div style={{ marginTop: "1rem", fontSize: "0.9em", color: "#666" }}>
                    <strong>出典：</strong>
                    <ul>
                      {sources.map((src, i) => (
                        <li key={i}>
                          <a
                            href={`https://rag-api-190389115361.asia-northeast1.run.app/pdfs/${encodeURIComponent(src.metadata.source)}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: "#1976d2", textDecoration: "underline" }}
                            title={`PDFを開く: ${src.metadata.source}`}
                          >
                            {src.metadata.source}
                          </a>
                          （p.{src.metadata.page}）
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
