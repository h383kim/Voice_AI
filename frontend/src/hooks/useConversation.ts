import { useCallback, useEffect, useRef, useState } from "react";
import {
  resumeVoiceTurn,
  streamVoiceTurn,
  type StreamHandlers,
  type TimingInfo,
  type ToolRequest,
} from "../api";
import { float32ToWav } from "../wav";

export type ConvState = "idle" | "listening" | "thinking" | "speaking" | "confirming";

// Ignore barge-in within this window after playback starts, so the assistant's
// own first audio (leaking into the mic) can't instantly self-interrupt.
const BARGE_IN_GRACE_MS = 350;

export function useConversation() {
  const [active, setActive] = useState(false);
  const [state, setState] = useState<ConvState>("idle");
  const [transcript, setTranscript] = useState("");
  const [assistantText, setAssistantText] = useState("");
  const [timing, setTiming] = useState<TimingInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<ToolRequest | null>(null);
  const [toolActivity, setToolActivity] = useState<string | null>(null);

  const vadRef = useRef<{ start: () => void; pause: () => void; destroy: () => void } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string | undefined>(undefined);

  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const queueRef = useRef<string[]>([]);
  const playingRef = useRef(false);
  const streamDoneRef = useRef(true);
  const playbackStartRef = useRef(0);
  const stateRef = useRef<ConvState>("idle");
  const activeRef = useRef(false);
  const pendingRef = useRef<ToolRequest | null>(null);

  const setConvState = useCallback((s: ConvState) => {
    stateRef.current = s;
    setState(s);
  }, []);

  const setActiveSync = useCallback((a: boolean) => {
    activeRef.current = a;
    setActive(a);
  }, []);

  const goListenOrIdle = useCallback(() => {
    if (activeRef.current) {
      vadRef.current?.start();
      setConvState("listening");
    } else {
      setConvState("idle");
    }
  }, [setConvState]);

  // --- audio queue ---
  const playNext = useCallback(() => {
    const el = audioElRef.current;
    if (!el) return;
    const next = queueRef.current.shift();
    if (!next) {
      playingRef.current = false;
      if (streamDoneRef.current && stateRef.current === "speaking") goListenOrIdle();
      return;
    }
    playingRef.current = true;
    if (stateRef.current !== "speaking") {
      setConvState("speaking");
      playbackStartRef.current = performance.now();
    }
    el.src = next;
    el.play().catch(() => {/* autoplay guard */});
  }, [goListenOrIdle, setConvState]);

  const enqueueAudio = useCallback((url: string) => {
    queueRef.current.push(url);
    if (!playingRef.current) playNext();
  }, [playNext]);

  const stopPlayback = useCallback(() => {
    queueRef.current = [];
    playingRef.current = false;
    const el = audioElRef.current;
    if (el) {
      el.pause();
      el.removeAttribute("src");
      el.load();
    }
  }, []);

  // --- shared SSE handlers (used by both stream and resume) ---
  const buildHandlers = useCallback((): StreamHandlers => ({
    onMeta: (sid) => { sessionIdRef.current = sid; },
    onTranscript: (text) => setTranscript(text),
    onDelta: (text) => setAssistantText((prev) => prev + text),
    onAudio: (url) => enqueueAudio(url),
    onTool: (tool) => {
      if (tool.status === "running") setToolActivity(`Running ${tool.name}…`);
      else setToolActivity(tool.ok === false ? `${tool.name} failed` : (tool.result || `${tool.name} done`));
    },
    onToolRequest: (req) => {
      vadRef.current?.pause();   // don't auto-listen while the dialog is up
      stopPlayback();
      pendingRef.current = req;
      setPendingAction(req);
      setConvState("confirming");
    },
    onError: (err) => {
      setError(err.message);
      streamDoneRef.current = true;
      if (!playingRef.current) goListenOrIdle();
    },
    onDone: (done) => {
      setTiming(done.timing);
      setAssistantText(done.assistant_response);
      streamDoneRef.current = true;
      if (!playingRef.current) goListenOrIdle();
    },
  }), [enqueueAudio, goListenOrIdle, setConvState, stopPlayback]);

  const startTurn = useCallback(async (audio: Blob) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setError(null);
    setAssistantText("");
    setTranscript("");
    setTiming(null);
    setToolActivity(null);
    streamDoneRef.current = false;
    setConvState("thinking");
    try {
      await streamVoiceTurn(audio, sessionIdRef.current, buildHandlers(), controller.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "Stream failed.");
      }
      streamDoneRef.current = true;
      if (!playingRef.current && stateRef.current !== "confirming") goListenOrIdle();
    }
  }, [buildHandlers, goListenOrIdle, setConvState]);

  const resolvePending = useCallback(async (approved: boolean) => {
    const req = pendingRef.current;
    if (!req) return;
    pendingRef.current = null;
    setPendingAction(null);
    const controller = new AbortController();
    abortRef.current = controller;
    streamDoneRef.current = false;
    setConvState("thinking");
    try {
      await resumeVoiceTurn(
        req.pending_id, approved, sessionIdRef.current, buildHandlers(), controller.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "Resume failed.");
      }
      streamDoneRef.current = true;
      if (!playingRef.current && stateRef.current !== "confirming") goListenOrIdle();
    }
  }, [buildHandlers, goListenOrIdle, setConvState]);

  // Barge-in: user talks while we're thinking/speaking.
  const handleSpeechStart = useCallback(() => {
    const busy = stateRef.current === "speaking" || stateRef.current === "thinking";
    const withinGrace =
      stateRef.current === "speaking" &&
      performance.now() - playbackStartRef.current < BARGE_IN_GRACE_MS;
    if (busy && !withinGrace) {
      abortRef.current?.abort();
      stopPlayback();
      streamDoneRef.current = true;
    }
    if (stateRef.current !== "confirming") setConvState("listening");
  }, [setConvState, stopPlayback]);

  const handleSpeechEnd = useCallback((audio: Float32Array) => {
    void startTurn(float32ToWav(audio, 16000));
  }, [startTurn]);

  const speechStartRef = useRef(handleSpeechStart);
  const speechEndRef = useRef(handleSpeechEnd);
  useEffect(() => { speechStartRef.current = handleSpeechStart; }, [handleSpeechStart]);
  useEffect(() => { speechEndRef.current = handleSpeechEnd; }, [handleSpeechEnd]);

  const ensureAudioEl = useCallback(() => {
    if (!audioElRef.current) {
      const el = new Audio();
      el.onended = () => playNext();
      audioElRef.current = el;
    }
  }, [playNext]);

  const start = useCallback(async () => {
    ensureAudioEl();
    if (vadRef.current) {
      vadRef.current.start();
      setActiveSync(true);
      setConvState("listening");
      return;
    }
    try {
      const { MicVAD } = await import("@ricky0123/vad-web");
      const vad = await MicVAD.new({
        onSpeechStart: () => speechStartRef.current(),
        onSpeechEnd: (audio: Float32Array) => speechEndRef.current(audio),
      });
      vadRef.current = vad as unknown as typeof vadRef.current;
      vad.start();
      setActiveSync(true);
      setConvState("listening");
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error ? `Could not start microphone/VAD: ${e.message}` : "Could not start microphone.",
      );
      setConvState("idle");
    }
  }, [ensureAudioEl, setActiveSync, setConvState]);

  const stop = useCallback(() => {
    vadRef.current?.pause();
    abortRef.current?.abort();
    stopPlayback();
    pendingRef.current = null;
    setPendingAction(null);
    setActiveSync(false);
    setConvState("idle");
  }, [setActiveSync, setConvState, stopPlayback]);

  // Upload fallback: one-off turn through the same streaming flow.
  const submitBlob = useCallback((blob: Blob) => {
    ensureAudioEl();
    void startTurn(blob);
  }, [ensureAudioEl, startTurn]);

  const approve = useCallback(() => resolvePending(true), [resolvePending]);
  const deny = useCallback(() => resolvePending(false), [resolvePending]);

  useEffect(() => () => {
    abortRef.current?.abort();
    vadRef.current?.destroy();
  }, []);

  return {
    active, state, transcript, assistantText, timing, error,
    pendingAction, toolActivity,
    start, stop, submitBlob, approve, deny,
  };
}
