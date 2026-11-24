"use client";

import { useState, useRef } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function MealPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>("");
  const [result, setResult] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setResult("");
  };

  const upload = async () => {
    if (!file) return;
    setIsLoading(true);
    setResult("");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API_BASE}/meal/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(JSON.stringify(data, null, 2));
    } catch (e: any) {
      setResult(`[Error] ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-4 space-y-6">
      <h1 className="text-2xl font-bold">📷 拍照记录餐食</h1>
      <p className="text-gray-500 text-sm">上传食物照片，AI 将识别食材并估算营养</p>

      {/* Upload area */}
      <div
        className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:border-blue-400"
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          onChange={handleFileChange}
          className="hidden"
        />
        {preview ? (
          <img src={preview} alt="preview" className="max-h-64 mx-auto rounded-lg" />
        ) : (
          <div className="text-gray-400">
            <p className="text-4xl mb-2">📷</p>
            <p>点击上传照片，或拖拽到此处</p>
            <p className="text-xs mt-1">支持手机拍照</p>
          </div>
        )}
      </div>

      {file && (
        <div className="flex gap-2">
          <button
            onClick={upload}
            disabled={isLoading}
            className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
          >
            {isLoading ? "识别中..." : "开始识别"}
          </button>
          <button
            onClick={() => { setFile(null); setPreview(""); setResult(""); }}
            className="px-6 py-2 border rounded-lg"
          >
            重新选择
          </button>
        </div>
      )}

      {result && (
        <div className="border rounded-lg p-4 bg-gray-50">
          <h3 className="font-semibold mb-2">识别结果</h3>
          <pre className="text-sm whitespace-pre-wrap">{result}</pre>
        </div>
      )}
    </div>
  );
}
