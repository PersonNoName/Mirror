import React from 'react';
import { BookOpen, Microscope, Trash2 } from 'lucide-react';
import { cn } from '@/src/lib/utils';

interface SkillCardProps {
  title: string;
  description: string;
  icon: 'book' | 'microscope';
  enabled?: boolean;
}

export const SkillCard: React.FC<SkillCardProps> = ({ title, description, icon, enabled = true }) => {
  const Icon = icon === 'book' ? BookOpen : Microscope;

  return (
    <div className="bg-surface rounded-2xl p-6 tactile-card hover:shadow-md transition-shadow group border-l-4 border-primary relative overflow-hidden">
      <div className="flex justify-between items-start mb-4">
        <div className="p-3 bg-primary/10 text-primary rounded-xl">
          <Icon size={24} />
        </div>
        {enabled && (
          <span className="px-2 py-1 bg-surface-container-highest text-secondary text-[10px] font-black uppercase tracking-widest rounded-md">
            Enabled
          </span>
        )}
      </div>
      <h4 className="font-headline font-bold text-lg text-on-surface mb-2">{title}</h4>
      <p className="font-body text-on-surface-variant text-base leading-relaxed mb-6">
        {description}
      </p>
      <div className="flex items-center gap-2">
        <button className="flex-1 py-2 bg-surface-container-high text-secondary font-bold text-xs rounded-lg hover:bg-secondary hover:text-on-secondary transition-colors">
          Edit Prompt
        </button>
        <button className="p-2 text-outline hover:text-red-800 transition-colors">
          <Trash2 size={18} />
        </button>
      </div>
    </div>
  );
};
