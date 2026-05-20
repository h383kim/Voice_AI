import type { ConvState } from "../hooks/useConversation";

interface MicControlProps {
  active: boolean;
  state: ConvState;
  toolActivity?: string | null;
  onStart: () => void;
  onStop: () => void;
  onUpload: (file: Blob) => void;
}

const STATUS_LABEL: Record<ConvState, string> = {
  idle: "Idle",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
  confirming: "Waiting for approval…",
};

export function MicControl({ active, state, toolActivity, onStart, onStop, onUpload }: MicControlProps) {
  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) onUpload(file);
  }

  return (
    <div className="recorder">
      <div className="row">
        {!active ? (
          <button className="primary" onClick={onStart}>
            Start conversation
          </button>
        ) : (
          <button onClick={onStop}>Stop</button>
        )}
        <span className={`pill ${state}`}>{STATUS_LABEL[state]}</span>
      </div>

      {toolActivity && <p className="tool-activity">{toolActivity}</p>}

      <div className="row">
        <label className="upload">
          or upload a clip
          <input
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.webm"
            onChange={onFileChange}
            disabled={active}
          />
        </label>
      </div>

      <p className="hint">
        Hands-free: just talk. It auto-detects when you stop, replies out loud, and you
        can interrupt by speaking again. Use headphones to avoid self-interruption.
      </p>
    </div>
  );
}
