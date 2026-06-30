"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { API_BASE_URL } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";

type Status = "connecting" | "waiting" | "connected" | "ended" | "error";

const STUN_SERVERS: RTCIceServer[] = [
  { urls: "stun:stun.l.google.com:19302" },
];

function wsUrl(appointmentId: string, token: string): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  return `${base}/api/v1/ws/consultations/${appointmentId}?token=${encodeURIComponent(token)}`;
}

/**
 * A peer-to-peer WebRTC consultation room. Media flows directly between the two
 * browsers; only SDP/ICE signaling is relayed through the backend WebSocket.
 * Exactly one side initiates the offer to avoid glare; the initiator re-sends
 * the offer periodically until the connection is established so join order does
 * not matter.
 */
export function ConsultRoom({
  appointmentId,
  initiator,
}: {
  appointmentId: string;
  initiator: boolean;
}) {
  const t = useTranslations("common");
  const token = useAuthStore((s) => s.token);

  const [status, setStatus] = useState<Status>("connecting");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const localVideoRef = useRef<HTMLVideoElement>(null);
  const remoteVideoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const offerTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = useCallback(() => {
    if (offerTimerRef.current) clearInterval(offerTimerRef.current);
    pcRef.current?.getSenders().forEach((s) => s.track?.stop());
    pcRef.current?.close();
    pcRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const hangUp = useCallback(() => {
    try {
      wsRef.current?.send(JSON.stringify({ type: "end" }));
    } catch {
      /* ignore */
    }
    cleanup();
    setStatus("ended");
  }, [cleanup]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    async function start() {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: true,
          audio: true,
        });
      } catch {
        setStatus("error");
        setErrorMsg("Camera and microphone access is required for the consultation.");
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((tr) => tr.stop());
        return;
      }
      if (localVideoRef.current) localVideoRef.current.srcObject = stream;

      const pc = new RTCPeerConnection({ iceServers: STUN_SERVERS });
      pcRef.current = pc;
      stream.getTracks().forEach((tr) => pc.addTrack(tr, stream));

      pc.ontrack = (event) => {
        if (remoteVideoRef.current) {
          remoteVideoRef.current.srcObject = event.streams[0];
          setStatus("connected");
        }
      };
      pc.onicecandidate = (event) => {
        if (event.candidate) {
          send({ type: "ice-candidate", candidate: event.candidate });
        }
      };
      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "connected") {
          if (offerTimerRef.current) clearInterval(offerTimerRef.current);
          setStatus("connected");
        }
      };

      const ws = new WebSocket(wsUrl(appointmentId, token!));
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("waiting");
        if (initiator) {
          void sendOffer();
          // Re-send the offer until connected, so join order is irrelevant.
          offerTimerRef.current = setInterval(() => {
            if (pc.connectionState !== "connected") void sendOffer();
          }, 3000);
        }
      };
      ws.onerror = () => {
        setStatus("error");
        setErrorMsg(t("serviceUnavailable"));
      };
      ws.onmessage = async (event) => {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case "offer":
            await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
            {
              const answer = await pc.createAnswer();
              await pc.setLocalDescription(answer);
              send({ type: "answer", sdp: answer });
            }
            break;
          case "answer":
            if (!pc.currentRemoteDescription) {
              await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
            }
            break;
          case "ice-candidate":
            try {
              await pc.addIceCandidate(new RTCIceCandidate(msg.candidate));
            } catch {
              /* ignore late candidates */
            }
            break;
          case "ended":
            cleanup();
            setStatus("ended");
            break;
          case "error":
            setStatus("error");
            setErrorMsg(msg.error?.message ?? "Unable to join the consultation.");
            break;
        }
      };

      async function sendOffer() {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        send({ type: "offer", sdp: offer });
      }
      function send(payload: unknown) {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
      }
    }

    void start();
    return () => {
      cancelled = true;
      cleanup();
    };
  }, [appointmentId, token, initiator, cleanup, t]);

  return (
    <div className="space-y-4">
      {status === "error" && errorMsg && <Notice tone="error">{errorMsg}</Notice>}
      {status === "ended" && (
        <Notice tone="info">The consultation has ended.</Notice>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="relative overflow-hidden rounded-2xl bg-ink">
          <video
            ref={remoteVideoRef}
            autoPlay
            playsInline
            className="aspect-video w-full bg-black object-cover"
            aria-label="Remote participant video"
          />
          <span className="absolute bottom-2 left-2 rounded bg-black/50 px-2 py-0.5 text-xs text-white">
            {status === "connected" ? "Connected" : t("loading")}
          </span>
        </div>
        <div className="relative overflow-hidden rounded-2xl bg-ink">
          <video
            ref={localVideoRef}
            autoPlay
            playsInline
            muted
            className="aspect-video w-full bg-black object-cover"
            aria-label="Your video"
          />
          <span className="absolute bottom-2 left-2 rounded bg-black/50 px-2 py-0.5 text-xs text-white">
            You
          </span>
        </div>
      </div>

      <div className="flex justify-center">
        <Button variant="danger" onClick={hangUp} disabled={status === "ended"}>
          End call
        </Button>
      </div>
    </div>
  );
}
