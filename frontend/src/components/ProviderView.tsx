import React, { useState } from 'react';
import { Cpu, Key, CheckCircle, Server, Zap, ChevronDown } from 'lucide-react';
import { cn } from '@/src/lib/utils';
import { motion } from 'motion/react';

const providers = [
  {
    id: 'gemini',
    name: 'Google Gemini',
    description: 'Advanced reasoning and multimodal capabilities.',
    status: 'connected',
    model: 'gemini-1.5-pro',
    models: ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.0-pro'],
    color: 'text-blue-500',
    bg: 'bg-blue-500/10',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'Industry standard language models and tool use.',
    status: 'available',
    model: 'gpt-4o',
    models: ['gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo'],
    color: 'text-emerald-500',
    bg: 'bg-emerald-500/10',
  },
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    description: 'Focus on constitutional AI and large context windows.',
    status: 'available',
    model: 'claude-3-opus-20240229',
    models: ['claude-3-opus-20240229', 'claude-3-sonnet-20240229', 'claude-3-haiku-20240307'],
    color: 'text-amber-500',
    bg: 'bg-amber-500/10',
  },
  {
    id: 'local',
    name: 'Local (Ollama)',
    description: 'Run models locally for complete privacy and offline use.',
    status: 'disconnected',
    model: 'llama3',
    models: ['llama3', 'mistral', 'phi3'],
    color: 'text-secondary',
    bg: 'bg-secondary/10',
  }
];

export const ProviderView: React.FC = () => {
  const [activeProvider, setActiveProvider] = useState('gemini');

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8 lg:p-12 space-y-8">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {providers.map((provider) => (
          <motion.div
            key={provider.id}
            whileHover={{ y: -4 }}
            className={cn(
              "bg-surface-container-low rounded-[2.5rem] p-6 md:p-8 tactile-card relative overflow-hidden border transition-all duration-300 cursor-pointer",
              activeProvider === provider.id 
                ? "border-primary shadow-lg ring-1 ring-primary/20" 
                : "border-surface-container-highest hover:border-primary/50"
            )}
            onClick={() => setActiveProvider(provider.id)}
          >
            <div className="grain-texture absolute inset-0 pointer-events-none" />
            <div className="relative z-10 flex flex-col h-full">
              <div className="flex justify-between items-start mb-6">
                <div className={cn("w-14 h-14 rounded-2xl flex items-center justify-center shadow-inner", provider.bg, provider.color)}>
                  <Cpu size={28} />
                </div>
                {provider.status === 'connected' && (
                  <span className="flex items-center gap-1.5 px-3 py-1 bg-green-500/10 text-green-600 rounded-full text-xs font-bold uppercase tracking-wider">
                    <CheckCircle size={14} /> Active
                  </span>
                )}
                {provider.status === 'available' && (
                  <span className="flex items-center gap-1.5 px-3 py-1 bg-surface-container-highest text-secondary/60 rounded-full text-xs font-bold uppercase tracking-wider">
                    Available
                  </span>
                )}
                {provider.status === 'disconnected' && (
                  <span className="flex items-center gap-1.5 px-3 py-1 bg-red-500/10 text-red-600 rounded-full text-xs font-bold uppercase tracking-wider">
                    Offline
                  </span>
                )}
              </div>
              
              <h3 className="text-2xl font-headline font-bold text-secondary mb-2">{provider.name}</h3>
              <p className="font-body text-secondary/70 mb-8 flex-1">{provider.description}</p>
              
              <div className="space-y-4 mt-auto">
                {/* Model Selector */}
                <div className="bg-surface rounded-xl p-3 flex items-center justify-between border border-surface-container-highest">
                  <div className="flex items-center gap-2 text-secondary/80">
                    <Zap size={16} />
                    <span className="font-label text-sm font-semibold">Model</span>
                  </div>
                  <div className="flex items-center gap-2 text-secondary font-body font-medium bg-surface-container px-3 py-1.5 rounded-lg cursor-pointer hover:bg-surface-container-highest transition-colors">
                    {provider.model}
                    <ChevronDown size={14} className="opacity-50" />
                  </div>
                </div>

                {/* API Key Input */}
                <div className="bg-surface rounded-xl p-3 flex items-center gap-3 border border-surface-container-highest">
                  <Key size={16} className="text-secondary/50 flex-shrink-0" />
                  <input 
                    type="password" 
                    placeholder="Enter API Key..." 
                    defaultValue={provider.status === 'connected' ? '••••••••••••••••••••••••' : ''}
                    className="bg-transparent border-none focus:ring-0 font-body text-sm text-secondary w-full outline-none placeholder:text-secondary/30"
                    onClick={(e) => e.stopPropagation()}
                  />
                  <button 
                    className="text-xs font-bold uppercase tracking-wider text-primary hover:text-primary/80 transition-colors"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {provider.status === 'connected' ? 'Update' : 'Save'}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
};
