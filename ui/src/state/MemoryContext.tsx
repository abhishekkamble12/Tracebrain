import React, { createContext, useContext, useState, useEffect } from 'react';

export interface MemoryState {
  memoryEnabled: boolean;
  setMemoryEnabled: (v: boolean) => void;
}

const MemoryContext = createContext<MemoryState | null>(null);

export const MemoryProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [memoryEnabled, setMemoryEnabledState] = useState<boolean>(() => {
    try {
      return localStorage.getItem('tracebrain.memoryEnabled') !== 'false';
    } catch {
      return true;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('tracebrain.memoryEnabled', String(memoryEnabled));
    } catch {
      /* ignore */
    }
  }, [memoryEnabled]);

  const setMemoryEnabled = (v: boolean) => setMemoryEnabledState(v);

  return (
    <MemoryContext.Provider value={{ memoryEnabled, setMemoryEnabled }}>
      {children}
    </MemoryContext.Provider>
  );
};

export function useMemory(): MemoryState {
  const ctx = useContext(MemoryContext);
  if (!ctx) throw new Error('useMemory must be used within MemoryProvider');
  return ctx;
}
