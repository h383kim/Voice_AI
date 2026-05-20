// Client for the LocalVoiceLab backend. In dev, Vite proxies /api to :8000,
// so relative URLs (including the returned audio_url) just work.

export interface TimingInfo {
  audio_save_ms: number;
  audio_normalization_ms: number;
  stt_ms: number;
  router_ms: number;
  llm_ms: number;
  tts_ms: number;
  first_audio_ms: number;
  total_ms: number;
}

export interface TurnMetadata {
  stt_model: string;
  llm_model: string;
  tts_engine: string;
  audio_duration_sec: number;
}

export interface VoiceTurnResponse {
  session_id: string;
  transcript: string;
  assistant_response: string;
  audio_url: string;
  timing: TimingInfo;
  metadata: TurnMetadata;
}

export interface ApiError {
  error: string;
  message: string;
}

export async function submitVoiceTurn(
  audio: Blob,
  sessionId?: string,
): Promise<VoiceTurnResponse> {
  const form = new FormData();
  const filename = audio instanceof File ? audio.name : "recording.webm";
  form.append("audio_file", audio, filename);
  if (sessionId) form.append("session_id", sessionId);

  const resp = await fetch("/api/voice-turn", { method: "POST", body: form });
  if (!resp.ok) {
    let detail: ApiError | null = null;
    try {
      detail = (await resp.json()) as ApiError;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail?.message || `Request failed (${resp.status})`);
  }
  return (await resp.json()) as VoiceTurnResponse;
}

// --- Streaming (SSE) client ---

export interface DoneEvent {
  assistant_response: string;
  timing: TimingInfo;
  metadata: TurnMetadata;
}

export interface ToolEvent {
  name: string;
  args?: Record<string, unknown>;
  result?: string;
  ok?: boolean;
  status: "running" | "done";
}

export interface ToolRequest {
  pending_id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface StreamHandlers {
  onMeta?: (sessionId: string) => void;
  onTranscript?: (text: string) => void;
  onDelta?: (text: string) => void;
  onAudio?: (url: string, text: string) => void;
  onTool?: (tool: ToolEvent) => void;
  onToolRequest?: (req: ToolRequest) => void;
  onDone?: (done: DoneEvent) => void;
  onError?: (err: ApiError) => void;
}

interface SSEEvent {
  event: string;
  data: string;
}

function parseSSEBlock(block: string): SSEEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

/**
 * POST audio and consume the SSE response, dispatching to handlers.
 * Pass an AbortSignal to support barge-in (cancel mid-stream).
 */
export async function streamVoiceTurn(
  audio: Blob,
  sessionId: string | undefined,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const form = new FormData();
  const filename = audio instanceof File ? audio.name : "utterance.wav";
  form.append("audio_file", audio, filename);
  if (sessionId) form.append("session_id", sessionId);

  const resp = await fetch("/api/voice-turn/stream", {
    method: "POST",
    body: form,
    signal,
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`Stream request failed (${resp.status})`);
  }

  await consumeSSE(resp.body.getReader(), handlers);
}

function dispatchSSE(evt: SSEEvent, handlers: StreamHandlers) {
  const payload = JSON.parse(evt.data);
  switch (evt.event) {
    case "meta":
      handlers.onMeta?.(payload.session_id);
      break;
    case "transcript":
      handlers.onTranscript?.(payload.text);
      break;
    case "delta":
      handlers.onDelta?.(payload.text);
      break;
    case "audio":
      handlers.onAudio?.(payload.url, payload.text);
      break;
    case "tool":
      handlers.onTool?.(payload as ToolEvent);
      break;
    case "tool_request":
      handlers.onToolRequest?.(payload as ToolRequest);
      break;
    case "done":
      handlers.onDone?.(payload as DoneEvent);
      break;
    case "error":
      handlers.onError?.(payload as ApiError);
      break;
  }
}

async function consumeSSE(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  handlers: StreamHandlers,
) {
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const evt = parseSSEBlock(block);
      if (evt) dispatchSSE(evt, handlers);
    }
  }
}

/** Continue a paused agent turn after the user approves/denies an action. */
export async function resumeVoiceTurn(
  pendingId: string,
  approved: boolean,
  sessionId: string | undefined,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch("/api/voice-turn/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pending_id: pendingId, approved, session_id: sessionId }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`Resume request failed (${resp.status})`);
  }
  await consumeSSE(resp.body.getReader(), handlers);
}
