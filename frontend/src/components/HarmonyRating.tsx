import React from 'react';
import { Sparkles } from 'lucide-react';

export const HarmonyRating: React.FC = () => {
  return (
    <div className="bg-surface-container rounded-[2.5rem] p-8 flex flex-col items-center text-center tactile-card h-full justify-center">
      <div className="w-20 h-20 bg-surface rounded-full flex items-center justify-center mb-4 shadow-inner recessed-field">
        <Sparkles size={36} className="text-primary fill-current" />
      </div>
      <h5 className="font-headline font-bold text-secondary mb-2">Harmony Rating: 94%</h5>
      <p className="text-xs text-secondary/70 font-label mb-6 px-4">
        Your prompt directives and MCP tools are exceptionally well-aligned.
      </p>
      <div className="w-full bg-surface-container-highest h-2.5 rounded-full overflow-hidden border border-secondary/5">
        <div 
          className="h-full bg-primary rounded-full shadow-[0_0_8px_rgba(45,90,39,0.3)] transition-all duration-1000" 
          style={{ width: '94%' }}
        />
      </div>
    </div>
  );
};
