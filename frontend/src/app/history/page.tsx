'use client';

import { useEffect, useState } from "react";

// --- 出典データ型 ---
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

export default function HistoryPage() {
  const [history, setHistory] = useState<ChatHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // アップロード用
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<string | null>(null);

  const fetchHistory = async () => {
    try {
      const res = await fetch("https://rag-api-190389115361.asia-northeast1.run.app/chat/history",);
      if (!res.ok) throw new Error(`API Error: ${res.status}`);
      const data = await res.json();
      setHistory(Array.isArray(data.logs) ? data.logs : []);
    } catch {
      setError("データ取得失敗");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  // アップロード
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    const formData = new FormData();
    formData.append("file", selectedFile);
    const res = await fetch("https://rag-api-190389115361.asia-northeast1.run.app/upload_pdf", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    setUploadResult(data.message);
    setSelectedFile(null);
    fetchHistory();
  };

  // --- エクスポートボタン ---
  const downloadCSV = async () => {
    const res = await fetch("https://rag-api-190389115361.asia-northeast1.run.app/chat/export/csv");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "chat_history.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };
  const downloadJSON = async () => {
    const res = await fetch("https://rag-api-190389115361.asia-northeast1.run.app/chat/export/json");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "chat_history.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  return (
    <div className="simple-container">
      <div className="simple-box" style={{ marginBottom: "2rem" }}>
        <h1 className="simple-title">履歴一覧</h1>
        {/* アップロード */}
        <div style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "1.1rem" }}>PDFアップロード</h2>
          <input type="file" accept="application/pdf" onChange={handleFileChange} />
          <button className="simple-button" onClick={handleUpload} disabled={!selectedFile} style={{ marginLeft: "1rem" }}>
            アップロード
          </button>
          {uploadResult && <div>{uploadResult}</div>}
        </div>
        {/* エクスポート */}
        <div style={{ marginBottom: "1.5rem" }}>
          <button className="simple-button" onClick={downloadCSV} style={{ marginRight: "1rem" }}>
            履歴CSVダウンロード
          </button>
          <button className="simple-button" onClick={downloadJSON}>
            履歴JSONダウンロード
          </button>
        </div>
        {/* 履歴リスト */}
        {loading && <div>読み込み中...</div>}
        {error && <div style={{ color: "red" }}>エラー: {error}</div>}
        {(!history || history.length === 0) && !loading && !error && <div>履歴がありません</div>}
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
                  {item.sources.map((src: Source, i: number) => (
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
  );
}
