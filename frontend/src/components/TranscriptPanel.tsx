interface TranscriptPanelProps {
  transcript: string;
  assistantResponse: string;
}

export function TranscriptPanel({ transcript, assistantResponse }: TranscriptPanelProps) {
  return (
    <div className="panel">
      <div className="bubble user">
        <span className="label">You said</span>
        <p>{transcript}</p>
      </div>
      <div className="bubble assistant">
        <span className="label">Assistant</span>
        <p>{assistantResponse}</p>
      </div>
    </div>
  );
}
