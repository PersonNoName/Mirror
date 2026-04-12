import React from 'react';
import { Database, Cloud, Terminal } from 'lucide-react';
import { cn } from '@/src/lib/utils';

interface MCPToolProps {
  name: string;
  status: string;
  icon: 'database' | 'cloud' | 'terminal';
  active?: boolean;
  paused?: boolean;
}

export const MCPTool: React.FC<MCPToolProps> = ({ name, status, icon, active, paused }) => {
  const Icon = icon === 'database' ? Database : icon === 'cloud' ? Cloud : Terminal;
  const iconColor = icon === 'database' ? 'text-blue-700 bg-blue-50' : icon === 'cloud' ? 'text-red-700 bg-red-50' : 'text-purple-700 bg-purple-50';

  return (
    <div className="bg-surface p-4 rounded-xl flex items-center gap-4 tactile-card group">
      <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center", iconColor)}>
        <Icon size={20} />
      </div>
      <div className="flex-1">
        <p className="font-bold text-sm text-on-surface">{name}</p>
        <p className="text-[11px] text-secondary/60">{status}</p>
      </div>
      {active && (
        <div className="w-2.5 h-2.5 rounded-full bg-green-600 shadow-[0_0_10px_rgba(22,163,74,0.4)]" />
      )}
      {!active && (
        <div className={cn(
          "w-8 h-4 rounded-full relative cursor-pointer transition-colors",
          paused ? "bg-primary" : "bg-surface-container-high"
        )}>
          <div className={cn(
            "absolute top-1 w-2 h-2 rounded-full transition-all",
            paused ? "right-1 bg-on-primary" : "left-1 bg-secondary/50"
          )} />
        </div>
      )}
    </div>
  );
};
