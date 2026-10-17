import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { useHealth, isTracebrainHealth } from '@/api/hooks';

/**
 * Explains, in one line, why nothing loads: the API is down, a different service answers on its
 * port, or FalkorDB is down. Hidden while healthy.
 */
export const ApiStatusBanner: React.FC = () => {
  const { data, isError, isLoading } = useHealth();
  if (isLoading) return null;

  let message: React.ReactNode = null;
  if (isError) {
    message = (
      <>
        Can't reach the Tracebrain API. Start it with{' '}
        <code className="font-mono">uv run uvicorn tracebrain.api.main:app --port 8000</code>; if that port is taken,
        use another one and set <code className="font-mono">TRACEBRAIN_API_URL</code> for the UI dev server.
      </>
    );
  } else if (!isTracebrainHealth(data)) {
    message = (
      <>
        The service behind <code className="font-mono">/api</code> isn't Tracebrain (another app is using that port).
        Run the Tracebrain API on a free port, then restart this dev server with{' '}
        <code className="font-mono">TRACEBRAIN_API_URL</code> set (PowerShell:{' '}
        <code className="font-mono">$env:TRACEBRAIN_API_URL="http://localhost:8010"; npm run dev</code>), or put it in{' '}
        <code className="font-mono">ui/.env.local</code>.
      </>
    );
  } else if (!data.falkordb) {
    message = <>The API is up but FalkorDB isn't reachable. Check FALKOR_HOST / FALKOR_PORT and that FalkorDB is running.</>;
  }

  if (!message) return null;
  return (
    <div role="alert" className="px-4 py-2 flex items-start gap-2 text-[12px] leading-relaxed bg-[var(--status-bad)]/10 border-b border-[var(--status-bad)]/30 text-[var(--text-primary)]">
      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--status-bad)]" />
      <p>{message}</p>
    </div>
  );
};
