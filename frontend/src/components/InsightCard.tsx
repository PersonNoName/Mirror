import React from 'react';

export const InsightCard: React.FC = () => {
  return (
    <div className="bg-secondary text-on-secondary rounded-[2.5rem] p-8 relative overflow-hidden group shadow-xl h-full flex flex-col justify-center">
      <img 
        src="https://picsum.photos/seed/wood-grain/800/600" 
        alt="Wood grain macro" 
        className="absolute inset-0 w-full h-full object-cover opacity-15 transition-transform duration-1000 group-hover:scale-110"
        referrerPolicy="no-referrer"
      />
      <div className="relative z-10">
        <h4 className="text-xl font-headline font-bold mb-4">Conservatory Insight</h4>
        <p className="font-body text-xl italic leading-relaxed mb-6 opacity-90">
          "Like a sapling, your AI grows toward the light you provide. Every skill added is a branch that expands its reach into the digital ether."
        </p>
        <div className="flex items-center gap-3">
          <div className="h-0.5 w-10 bg-on-secondary/40 rounded-full" />
          <span className="text-[10px] font-black tracking-[0.2em] uppercase opacity-70">
            Ancient Wisdom Module
          </span>
        </div>
      </div>
    </div>
  );
};
