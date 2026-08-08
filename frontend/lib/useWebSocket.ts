"use client";
import { useEffect, useRef } from "react";
import { auth } from "@/lib/api";

export function useWebSocket(onMessage: (data: unknown) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let stopped = false;

    const connect = () => {
      const token = auth.token();
      if (!token || stopped) return;

      // In production set NEXT_PUBLIC_WS_URL to the backend's public WebSocket
      // endpoint, e.g. "wss://fms-backend.up.railway.app/ws". Unset falls back to
      // the local dev backend on :8002, so `npm run dev` is unchanged.
      const configured = process.env.NEXT_PUBLIC_WS_URL;
      let wsUrl: string;
      if (configured) {
        const sep = configured.includes("?") ? "&" : "?";
        wsUrl = `${configured}${sep}token=${encodeURIComponent(token)}`;
      } else {
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const host = window.location.hostname || "localhost";
        wsUrl = `${protocol}://${host}:8002/ws?token=${encodeURIComponent(token)}`;
      }
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (e) => {
        try {
          onMessage(JSON.parse(e.data));
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!stopped) reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();
    return () => {
      stopped = true;
      wsRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [onMessage]);
}
