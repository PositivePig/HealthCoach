"use client";

import { useState, useRef, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  provider?: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    const assistantMessage: Message = {
      id: (Date.now() + 1).toString(),
      role: "assistant",
      content: "",
    };
    setMessages((prev) => [...prev, assistantMessage]);

    try {
      const url = `${API_BASE}/chat/stream?message=${encodeURIComponent(input)}`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) throw new Error("No reader");

      let buf = "";
      let done = false;

      while (!done) {
        const { done: readerDone, value } = await reader.read();
        done = readerDone;
        if (value) {
          buf += decoder.decode(value, { stream: true });
        }

        const lines = buf.split("\n");
        buf = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            if (dataStr === "{}") continue;
            try {
              const data = JSON.parse(dataStr);
              if (data.delta) {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === "assistant") {
                    last.content += data.delta;
                    if (data.provider) last.provider = data.provider;
                  }
                  return updated;
                });
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    } catch {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.role === "assistant") {
          last.content = "[Error: Failed to connect to backend. Is it running on port 8000?]";
        }
        return updated;
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex flex-col h-screen max-w-4xl mx-auto p-4">
      <header className="mb-4">
        <h1 className="text-2xl font-bold">🏥 HealthCoach Agent</h1>
        <p className="text-sm text-gray-500">Your proactive multimodal health coach</p>
      </header>

      <div className="flex-1 overflow-y-auto p-4 mb-4 space-y-4 border rounded-lg bg-gray-50">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 mt-20">
            <p className="text-lg">👋 Start a conversation!</p>
            <p className="text-sm mt-2">Try: &quot;I want to lose fat, help me plan my meals&quot;</p>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2 ${
                msg.role === "user"
                  ? "bg-blue-500 text-white"
                  : "bg-white text-gray-900 border"
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content || "..."}</p>
              {msg.provider && msg.role === "assistant" && (
                <p className="text-xs opacity-50 mt-1">via {msg.provider}</p>
              )}
            </div>
          </div>
        ))}

        {isLoading && messages[messages.length - 1]?.role === "assistant" && (
          <div className="flex justify-start">
            <div className="bg-white border rounded-lg px-4 py-2">
              <span className="animate-pulse">● ● ●</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message... (Enter to send)"
          disabled={isLoading}
          className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={sendMessage}
          disabled={isLoading || !input.trim()}
          className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
        >
          Send
        </button>
      </div>

      <div className="text-xs text-gray-400 mt-2 text-center">
        Backend: {API_BASE} | Status: {isLoading ? "streaming..." : "ready"}
      </div>
    </div>
  );
}
