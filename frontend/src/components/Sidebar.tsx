import React from 'react';
import { MessageSquare, LayoutGrid, Settings, PlusCircle, Cpu, Globe, Scroll } from 'lucide-react';
import { cn } from '@/src/lib/utils';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab }) => {
  const navItems = [
    { id: 'chat', label: 'Chat', icon: MessageSquare },
    { id: 'prompt', label: 'Core Prompt', icon: Scroll, hideOnMobile: true },
    { id: 'skills', label: 'Skills & MCP', icon: LayoutGrid, hideOnMobile: true },
    { id: 'provider', label: 'Provider', icon: Cpu },
    { id: 'platform', label: 'Platform', icon: Globe },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <>
      {/* Mobile Bottom Nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-surface-container-low border-t border-surface-container-highest z-50 px-6 py-3 flex justify-around items-center shadow-[0_-10px_30px_rgba(93,64,55,0.05)]">
        {navItems.filter(item => !item.hideOnMobile).map((item) => (
          <button
            key={item.id}
            onClick={() => setActiveTab(item.id)}
            className={cn(
              "flex flex-col items-center gap-1 transition-all duration-300",
              activeTab === item.id ? "text-primary" : "text-secondary/50"
            )}
          >
            <item.icon size={24} className={cn(activeTab === item.id && "fill-current")} />
            <span className="text-[10px] font-bold uppercase tracking-wider">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Desktop Sidebar */}
      <aside className="hidden md:flex fixed left-0 top-0 h-full flex-col p-4 z-40 bg-surface-container-low w-72 rounded-r-3xl border-r border-surface-container-highest shadow-[10px_0_30px_rgba(93,64,55,0.05)] font-label text-sm tracking-wide">
      <div className="flex items-center gap-3 mb-10 px-2">
        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center text-on-primary shadow-lg overflow-hidden">
          <img 
            src="https://picsum.photos/seed/forest-spirit/100/100" 
            alt="Forest spirit icon" 
            className="w-full h-full object-cover"
            referrerPolicy="no-referrer"
          />
        </div>
        <div>
          <h1 className="text-lg font-headline font-bold text-secondary">The Study</h1>
          <p className="text-[10px] uppercase tracking-[0.2em] text-secondary/60 font-bold">AI Companion</p>
        </div>
      </div>

      <nav className="flex-1 space-y-2">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => setActiveTab(item.id)}
            className={cn(
              "w-full flex items-center gap-3 px-4 py-3 rounded-2xl transition-all duration-300",
              activeTab === item.id 
                ? "bg-primary text-on-primary shadow-md scale-[0.98]" 
                : "text-secondary/70 hover:bg-surface-container-highest"
            )}
          >
            <item.icon size={20} className={cn(activeTab === item.id && "fill-current")} />
            <span className={cn(activeTab === item.id && "font-semibold")}>{item.label}</span>
          </button>
        ))}
      </nav>

      <button className="mt-auto mb-4 w-full py-4 bg-secondary text-on-secondary rounded-2xl font-bold flex items-center justify-center gap-2 shadow-lg hover:shadow-xl hover:translate-y-[-2px] transition-all duration-300">
        <PlusCircle size={20} />
        <span>New Growth</span>
      </button>
    </aside>
    </>
  );
};
