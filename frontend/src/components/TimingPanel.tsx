import type { TimingInfo } from "../api";

interface TimingPanelProps {
  timing: TimingInfo;
}

export function TimingPanel({ timing }: TimingPanelProps) {
  const rows: [string, number][] = [
    ["STT", timing.stt_ms],
    ["LLM", timing.llm_ms],
    ["TTS", timing.tts_ms],
    ["First audio", timing.first_audio_ms],
    ["Total", timing.total_ms],
  ];
  return (
    <div className="panel timing">
      <span className="label">Latency</span>
      <table>
        <tbody>
          {rows.map(([name, ms]) => (
            <tr key={name}>
              <td>{name}</td>
              <td>{Math.round(ms)} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
