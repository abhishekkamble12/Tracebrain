import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '@/features/shell/AppShell';
import { ConsolePage } from '@/features/console/ConsolePage';
import { MemoryPage } from '@/features/memory/MemoryPage';
import { ResultsPage } from '@/features/results/ResultsPage';

// ConsolePage owns its SelectionProvider, keyed per run (see ConsolePage).
const ConsoleWithContext = () => <ConsolePage />;

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/t/payments" replace />,
  },
  {
    path: '/t/:tenant',
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <ConsoleWithContext />,
      },
      {
        path: 'incidents/:incidentId',
        element: <ConsoleWithContext />,
      },
      {
        path: 'incidents/:incidentId/runs/:invId',
        element: <ConsoleWithContext />,
      },
      {
        path: 'memory',
        element: <MemoryPage />,
      },
    ],
  },
  {
    path: '/results',
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <ResultsPage />,
      },
    ],
  },
  {
    path: '*',
    element: (
      <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--bg-canvas)] text-[var(--text-primary)] gap-4 p-6">
        <h1 className="text-3xl font-mono font-bold text-[var(--accent)]">404</h1>
        <p className="text-sm text-[var(--text-secondary)]">The requested view does not exist.</p>
        <a
          href="/"
          className="px-4 py-2 rounded bg-[var(--accent)] text-[var(--text-inverse)] text-xs font-semibold hover:opacity-90"
        >
          Return to Console
        </a>
      </div>
    ),
  },
]);
