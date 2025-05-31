"use client";
import { useState } from "react";

export default function ApiTest() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState("");

  const ask = async () => {
    const res = await fetch("https://rag-api-190389115361.asia-northeast1.run.app/chat", { // ←修正！
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: query }), // ←修正！
      credentials: "include",
    });
    const data = await res.json();
    setResult(data.answer ?? JSON.stringify(data));
  };

  return (
    <div className="p-8 max-w-xl mx-auto">
      <h1 className="text-xl font-bold mb-4">RAG API 疎通テスト</h1>
      <textarea
        className="border w-full p-2 rounded"
        rows={3}
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="ここに質問を入力"
      />
      <button
        className="bg-blue-500 text-white px-4 py-2 rounded mt-2"
        onClick={ask}
      >
        送信
      </button>
      <div className="mt-4 border p-2 min-h-[48px] whitespace-pre-line">
        {result}
      </div>
    </div>
  );
}
