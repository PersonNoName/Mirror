import React, { useState } from 'react';
import { Globe, MessageCircle, Hash, Send, Link as LinkIcon, CheckCircle, AlertCircle } from 'lucide-react';
import { cn } from '@/src/lib/utils';
import { motion } from 'motion/react';

const platforms = [
  {
    id: 'telegram',
    name: 'Telegram',
    description: 'Connect your agent to a Telegram bot for mobile access.',
    status: 'connected',
    icon: Send,
    color: 'text-sky-500',
    bg: 'bg-sky-500/10',
    fields: [
      { label: 'Bot Token', type: 'password', value: '••••••••••••••••••••••••' },
      { label: 'Bot Username', type: 'text', value: '@SylvanAgentBot' }
    ]
  },
  {
    id: 'feishu',
    name: 'Feishu / Lark',
    description: 'Integrate with enterprise workspaces and group chats.',
    status: 'available',
    icon: MessageCircle,
    color: 'text-teal-500',
    bg: 'bg-teal-500/10',
    fields: [
      { label: 'App ID', type: 'text', value: '' },
      { label: 'App Secret', type: 'password', value: '' },
      { label: 'Verification Token', type: 'password', value: '' }
    ]
  },
  {
    id: 'discord',
    name: 'Discord',
    description: 'Deploy your agent to Discord servers and channels.',
    status: 'available',
    icon: Hash,
    color: 'text-indigo-500',
    bg: 'bg-indigo-500/10',
    fields: [
      { label: 'Bot Token', type: 'password', value: '' },
      { label: 'Application ID', type: 'text', value: '' }
    ]
  },
  {
    id: 'slack',
    name: 'Slack',
    description: 'Bring your agent into Slack workspaces.',
    status: 'available',
    icon: Hash,
    color: 'text-rose-500',
    bg: 'bg-rose-500/10',
    fields: [
      { label: 'Bot User OAuth Token', type: 'password', value: '' },
      { label: 'Signing Secret', type: 'password', value: '' }
    ]
  }
];

export const PlatformView: React.FC = () => {
  return (
    <div className="h-full overflow-y-auto p-4 md:p-8 lg:p-12 space-y-8">
      <div className="bg-surface-container-low rounded-[2.5rem] p-6 md:p-8 tactile-card relative overflow-hidden mb-8">
        <div className="grain-texture absolute inset-0 pointer-events-none" />
        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div>
            <h3 className="text-2xl font-headline font-bold text-secondary mb-2">Global Webhook</h3>
            <p className="font-body text-secondary/70">Use this URL to receive events from connected platforms.</p>
          </div>
          <div className="w-full md:w-auto bg-surface rounded-xl p-3 flex items-center gap-3 border border-surface-container-highest">
            <LinkIcon size={16} className="text-secondary/50 flex-shrink-0" />
            <code className="font-mono text-sm text-secondary truncate max-w-[200px] md:max-w-[300px]">
              https://api.sylvan.ai/webhook/v1/nexus
            </code>
            <button className="text-xs font-bold uppercase tracking-wider text-primary hover:text-primary/80 transition-colors ml-2">
              Copy
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {platforms.map((platform) => (
          <motion.div
            key={platform.id}
            whileHover={{ y: -4 }}
            className="bg-surface-container-low rounded-[2.5rem] p-6 md:p-8 tactile-card relative overflow-hidden border border-surface-container-highest transition-all duration-300"
          >
            <div className="grain-texture absolute inset-0 pointer-events-none" />
            <div className="relative z-10 flex flex-col h-full">
              <div className="flex justify-between items-start mb-6">
                <div className={cn("w-14 h-14 rounded-2xl flex items-center justify-center shadow-inner", platform.bg, platform.color)}>
                  <platform.icon size={28} />
                </div>
                {platform.status === 'connected' ? (
                  <span className="flex items-center gap-1.5 px-3 py-1 bg-green-500/10 text-green-600 rounded-full text-xs font-bold uppercase tracking-wider">
                    <CheckCircle size={14} /> Active
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 px-3 py-1 bg-surface-container-highest text-secondary/60 rounded-full text-xs font-bold uppercase tracking-wider">
                    Available
                  </span>
                )}
              </div>
              
              <h3 className="text-2xl font-headline font-bold text-secondary mb-2">{platform.name}</h3>
              <p className="font-body text-secondary/70 mb-8 flex-1">{platform.description}</p>
              
              <div className="space-y-3 mt-auto">
                {platform.fields.map((field, idx) => (
                  <div key={idx} className="bg-surface rounded-xl p-3 flex flex-col gap-1 border border-surface-container-highest">
                    <label className="text-[10px] uppercase tracking-wider font-bold text-secondary/50 px-1">
                      {field.label}
                    </label>
                    <input 
                      type={field.type} 
                      placeholder={`Enter ${field.label}...`}
                      defaultValue={field.value}
                      className="bg-transparent border-none focus:ring-0 font-body text-sm text-secondary w-full outline-none placeholder:text-secondary/30 px-1"
                    />
                  </div>
                ))}
                
                <button className={cn(
                  "w-full mt-4 py-3 rounded-xl font-bold text-sm transition-all shadow-sm",
                  platform.status === 'connected' 
                    ? "bg-surface-container-highest text-secondary hover:bg-surface-container-highest/80" 
                    : "bg-primary text-on-primary hover:bg-primary/90"
                )}>
                  {platform.status === 'connected' ? 'Disconnect' : 'Connect Platform'}
                </button>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
};
