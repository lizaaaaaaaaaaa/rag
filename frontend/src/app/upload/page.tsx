'use client';

import { useState } from "react";

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    const formData = new FormData();
    formData.append("file", selectedFile);
    const res = await fetch("http://localhost:8000/upload_pdf", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    setResult(data.message);
    setSelectedFile(null); // アップロード後に選択解除
  };

  return (
    <div style={{ padding: "2rem" }}>
      <h2>PDFアップロード</h2>
      <input type="file" accept="application/pdf" onChange={handleFileChange} />
      <button onClick={handleUpload} disabled={!selectedFile}>
        アップロード
      </button>
      {result && <div>{result}</div>}
    </div>
  );
}
