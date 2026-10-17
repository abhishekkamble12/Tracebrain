import React from 'react';
import { Keyboard, X } from 'lucide-react';

interface ShortcutSheetProps {
  open: boolean;
  onClose: () => void;
}

interface ShortcutItem {
  keys: string[];
  desc: string;
}

const SHORTCUT_GROUPS: { group: string; items: ShortcutItem[] }[] = [
  {
    group: 'Investigation & Controls',
    items: [
      { keys: ['I'], desc: 'Start investigation for selected incident' },
      { keys: ['R'], desc: 'Resume interrupted investigation' },
      { keys: ['M'], desc: 'Toggle institutional memory ON / OFF' },
      { keys: ['T'], desc: 'Toggle topology mode (As-Of vs Now)' },
    ],
  },
  {
    group: 'Inspector Tabs',
    items: [
      { keys: ['1'], desc: 'Switch to Live Trace tab' },
      { keys: ['2'], desc: 'Switch to Evidence & Hypotheses tab' },
      { keys: ['3'], desc: 'Switch to Proposed Actions tab' },
    ],
  },
  {
    group: 'Graph Stage',
    items: [
      { keys: ['Esc'], desc: 'Clear pinned edges & dismiss modals' },
      { keys: ['Space + Drag'], desc: 'Pan topology canvas' },
      { keys: ['Scroll'], desc: 'Zoom canvas in / out' },
    ],
  },
  {
    group: 'Navigation',
    items: [
      { keys: ['?'], desc: 'Toggle keyboard shortcut cheat-sheet' },
      { keys: ['Alt', '1'], desc: 'Go to Console page' },
      { keys: ['Alt', '2'], desc: 'Go to Institutional Memory' },
      { keys: ['Alt', '3'], desc: 'Go to Benchmark Results' },
    ],
  },
];

export const ShortcutSheet: React.FC<ShortcutSheetProps> = ({ open, onClose }) => {
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '?' && !e.ctrlKey && !e.metaKey && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        if (open) onClose();
      } else if (e.key === 'Escape' && open) {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-150">
      <div className="w-full max-w-lg rounded-xl border border-[var(--border-strong)] bg-[var(--surface-panel)] p-6 shadow-2xl flex flex-col gap-5">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border-subtle)] pb-3">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded bg-[var(--accent)]/15 text-[var(--accent)]">
              <Keyboard className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">Keyboard Shortcuts</h2>
              <p className="text-[11px] text-[var(--text-faint)]">Accelerate root-cause analysis operations</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-[var(--text-faint)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Shortcut Groups */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[60vh] overflow-y-auto pr-1">
          {SHORTCUT_GROUPS.map((grp) => (
            <div key={grp.group} className="flex flex-col gap-2">
              <h3 className="text-[10px] font-mono uppercase tracking-wider text-[var(--accent)] font-semibold">
                {grp.group}
              </h3>
              <div className="flex flex-col gap-1.5">
                {grp.items.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between py-1 px-1.5 rounded bg-[var(--surface-card)] border border-[var(--border-subtle)] text-xs"
                  >
                    <span className="text-[11px] text-[var(--text-secondary)]">{item.desc}</span>
                    <div className="flex items-center gap-1">
                      {item.keys.map((k) => (
                        <kbd
                          key={k}
                          className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--surface-hover)] border border-[var(--border-strong)] text-[var(--text-primary)] shadow-xs"
                        >
                          {k}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="border-t border-[var(--border-subtle)] pt-3 flex items-center justify-between text-[11px] text-[var(--text-faint)]">
          <span>Press <kbd className="px-1 py-0.5 rounded bg-[var(--surface-card)] border font-mono">?</kbd> anywhere to toggle</span>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1 rounded bg-[var(--surface-card)] hover:bg-[var(--surface-hover)] text-xs text-[var(--text-primary)] border border-[var(--border-subtle)] transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
};
