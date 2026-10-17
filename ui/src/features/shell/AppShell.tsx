import React from 'react';
import { Outlet } from 'react-router-dom';
import { TopBar } from './TopBar';
import { ShortcutSheet } from './ShortcutSheet';
import { ApiStatusBanner } from './ApiStatusBanner';
import { Toaster } from 'sonner';
import { MemoryProvider } from '@/state/MemoryContext';

export const AppShell: React.FC = () => {
  const [shortcutsOpen, setShortcutsOpen] = React.useState(false);

  // `?` opens the shortcut sheet (the sheet itself handles closing)
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey && tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
        setShortcutsOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <MemoryProvider>
      <div className="min-h-screen h-screen flex flex-col bg-[var(--bg-canvas)] text-[var(--text-primary)] overflow-hidden">
        <TopBar onOpenShortcuts={() => setShortcutsOpen(true)} />
        <ApiStatusBanner />
        <main className="flex-1 flex overflow-hidden relative">
          <Outlet />
        </main>
        <ShortcutSheet open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
        <Toaster
          theme="dark"
          position="bottom-center"
          toastOptions={{
            style: {
              background: 'var(--surface-card)',
              border: '1px solid var(--border-strong)',
              color: 'var(--text-primary)',
              fontFamily: 'Geist Variable, sans-serif',
            },
          }}
        />
      </div>
    </MemoryProvider>
  );
};
