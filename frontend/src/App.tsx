import "./styles.css";
import { useConversation } from "./hooks/useConversation";
import { MicControl } from "./components/MicControl";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { TimingPanel } from "./components/TimingPanel";

export function App() {
  const conv = useConversation();

  return (
    <div className="app">
      <header>
        <h1>LocalVoiceLab</h1>
        <p className="subtitle">
          Real-time, hands-free local voice assistant — talk and it talks back, and it
          can act on your Mac.
        </p>
      </header>

      <MicControl
        active={conv.active}
        state={conv.state}
        toolActivity={conv.toolActivity}
        onStart={conv.start}
        onStop={conv.stop}
        onUpload={conv.submitBlob}
      />

      {conv.pendingAction && (
        <ConfirmDialog
          request={conv.pendingAction}
          onAllow={conv.approve}
          onDeny={conv.deny}
        />
      )}

      {conv.error && <p className="error">{conv.error}</p>}

      {(conv.transcript || conv.assistantText) && (
        <TranscriptPanel
          transcript={conv.transcript}
          assistantResponse={conv.assistantText}
        />
      )}

      {conv.timing && <TimingPanel timing={conv.timing} />}
    </div>
  );
}
