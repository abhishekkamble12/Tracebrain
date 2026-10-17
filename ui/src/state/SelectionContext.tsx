import React, { createContext, useContext, useState } from 'react';

export interface SelectionState {
  focusedHypothesisRank: number | null;       // 1-indexed
  hoveredClaimEdgeIds: number[];
  pinnedEdgeIds: number[];
  activeTopoMode: 'asof' | 'now';
  scrubbedTimestamp: number | null;
}

export interface SelectionActions {
  setFocusedHypothesis: (rank: number | null) => void;
  setHoveredClaimEdgeIds: (ids: number[]) => void;
  pinEdges: (ids: number[]) => void;
  clearPinnedEdges: () => void;
  setTopoMode: (mode: 'asof' | 'now') => void;
  setScrubbedTimestamp: (ts: number | null) => void;
}

const SelectionContext = createContext<(SelectionState & SelectionActions) | null>(null);

export const SelectionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [focusedHypothesisRank, setFocusedHypothesis] = useState<number | null>(null);
  const [hoveredClaimEdgeIds, setHoveredClaimEdgeIds] = useState<number[]>([]);
  const [pinnedEdgeIds, setPinnedEdgeIds] = useState<number[]>([]);
  const [activeTopoMode, setTopoMode] = useState<'asof' | 'now'>('asof');
  const [scrubbedTimestamp, setScrubbedTimestamp] = useState<number | null>(null);

  const pinEdges = (ids: number[]) => setPinnedEdgeIds(ids);
  const clearPinnedEdges = () => setPinnedEdgeIds([]);

  return (
    <SelectionContext.Provider
      value={{
        focusedHypothesisRank,
        hoveredClaimEdgeIds,
        pinnedEdgeIds,
        activeTopoMode,
        scrubbedTimestamp,
        setFocusedHypothesis,
        setHoveredClaimEdgeIds,
        pinEdges,
        clearPinnedEdges,
        setTopoMode,
        setScrubbedTimestamp,
      }}
    >
      {children}
    </SelectionContext.Provider>
  );
};

export function useSelection(): SelectionState & SelectionActions {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error('useSelection must be used within SelectionProvider');
  return ctx;
}
