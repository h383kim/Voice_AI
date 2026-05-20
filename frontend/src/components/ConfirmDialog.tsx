import type { ToolRequest } from "../api";

interface ConfirmDialogProps {
  request: ToolRequest;
  onAllow: () => void;
  onDeny: () => void;
}

function describe(req: ToolRequest): string {
  const args = req.args || {};
  if (req.name === "open_url") return `Open this URL: ${args.url}`;
  if (req.name === "open_app") return `Launch this app: ${args.name}`;
  if (req.name === "send_imessage") {
    const who = (args.display_name as string) || (args.to as string);
    return `Send iMessage to ${who}: "${args.message}"`;
  }
  return `${req.name}(${JSON.stringify(args)})`;
}

export function ConfirmDialog({ request, onAllow, onDeny }: ConfirmDialogProps) {
  return (
    <div className="confirm">
      <span className="label">Allow this action?</span>
      <p className="action">{describe(request)}</p>
      <div className="row">
        <button className="primary" onClick={onAllow}>Allow</button>
        <button onClick={onDeny}>Deny</button>
      </div>
    </div>
  );
}
