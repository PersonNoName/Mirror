import React, { useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { SkillCard } from './components/SkillCard';
import { MCPTool } from './components/MCPTool';
import { PromptEditor } from './components/PromptEditor';
import { ProviderView } from './components/ProviderView';
import { PlatformView } from './components/PlatformView';
import { InsightCard } from './components/InsightCard';
import { HarmonyRating } from './components/HarmonyRating';
import { ChatView } from './components/ChatView';
import { Brain, Plus, Settings, MessageSquare, Cpu, Globe } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export default function App() {
  const [activeTab, setActiveTab] = useState('chat');

  return (
    <div className="min-h-screen bg-background text-on-surface font-label selection:bg-primary/30 selection:text-primary">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="md:ml-72 h-screen relative flex flex-col overflow-hidden pb-16 md:pb-0">
        <header className="flex-shrink-0 z-30 px-6 md:px-12 py-4 md:py-6 flex justify-between items-center bg-background/90 backdrop-blur-sm border-b border-surface-container-highest/20">
          <div className="max-w-2xl">
            <h2 className="text-2xl md:text-4xl font-headline font-bold text-secondary tracking-tight mb-0.5 md:mb-1">
              {activeTab === 'chat' ? 'The Study' : 
               activeTab === 'provider' ? 'The Engine' :
               activeTab === 'platform' ? 'The Nexus' :
               activeTab === 'prompt' ? 'The Constitution' :
               'The Conservatory'}
            </h2>
            <p className="font-body text-sm md:text-lg text-secondary/80 italic line-clamp-1">
              {activeTab === 'chat' 
                ? 'Deepening the connection through shared dialogue.' 
                : activeTab === 'provider'
                ? 'Managing the underlying intelligence frameworks.'
                : activeTab === 'platform'
                ? 'Integrating with the wider digital ecosystem.'
                : activeTab === 'prompt'
                ? 'Defining the foundational directives that shape behavior.'
                : 'Nurturing the logic and capabilities of your Sylvan companion.'}
            </p>
          </div>
          <div className="flex items-center gap-2 md:gap-4">
            <button className="p-2 md:p-3 rounded-full hover:bg-surface-container transition-colors text-secondary">
              <Brain size={20} className="md:w-6 md:h-6" />
            </button>
            <div className="h-10 w-10 md:h-12 md:w-12 rounded-full border-2 border-primary p-0.5 shadow-sm overflow-hidden">
              <img 
                src="https://picsum.photos/seed/botanical-avatar/100/100" 
                alt="User botanical avatar" 
                className="w-full h-full rounded-full object-cover"
                referrerPolicy="no-referrer"
              />
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-hidden">
          <AnimatePresence mode="wait">
            {activeTab === 'chat' && (
              <motion.div
                key="chat"
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.4 }}
                className="h-full md:p-8 lg:p-12"
              >
                <ChatView />
              </motion.div>
            )}

            {activeTab === 'prompt' && (
              <motion.div
                key="prompt"
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.4 }}
                className="h-full overflow-y-auto p-8 lg:p-12"
              >
                <div className="max-w-4xl mx-auto">
                  <PromptEditor />
                </div>
              </motion.div>
            )}

            {activeTab === 'provider' && (
              <motion.div
                key="provider"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="h-full"
              >
                <ProviderView />
              </motion.div>
            )}

            {activeTab === 'platform' && (
              <motion.div
                key="platform"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="h-full"
              >
                <PlatformView />
              </motion.div>
            )}

            {activeTab === 'skills' && (
              <motion.div
                key="skills"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="h-full overflow-y-auto p-8 lg:p-12"
              >
                <div className="grid grid-cols-12 gap-8">
                  {/* Left Column */}
                  <div className="col-span-12 lg:col-span-8 space-y-8">
                    {/* Active Skillsets Section */}
                    <div className="bg-surface-container-low rounded-[2.5rem] p-8 tactile-card relative overflow-hidden">
                      <div className="grain-texture absolute inset-0 pointer-events-none" />
                      <div className="relative z-10">
                        <div className="flex justify-between items-end mb-8">
                          <div>
                            <h3 className="text-2xl font-headline font-bold text-secondary mb-1">Active Skillsets</h3>
                            <p className="font-body text-secondary/70 text-lg">Current cognitive frameworks in use.</p>
                          </div>
                          <button className="px-6 py-2 bg-secondary text-on-secondary rounded-xl font-bold text-sm shadow-md hover:bg-secondary/90 transition-colors">
                            Prune & Organize
                          </button>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                          <SkillCard 
                            title="Narrative Weaver"
                            description="Capable of complex storytelling, character continuity, and atmospheric world-building."
                            icon="book"
                          />
                          <SkillCard 
                            title="Botanical Logic"
                            description="Specialized in recursive systems, growth patterns, and biological metaphors for problem solving."
                            icon="microscope"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Master Prompt Editor Section */}
                    <PromptEditor />
                  </div>

                  {/* Right Column */}
                  <div className="col-span-12 lg:col-span-4 space-y-8">
                    {/* MCP Tools Section */}
                    <div className="bg-surface-container-low rounded-[2.5rem] p-8 tactile-card relative overflow-hidden border border-surface-container-high">
                      <div className="grain-texture absolute inset-0 pointer-events-none" />
                      <div className="relative z-10">
                        <div className="flex items-center gap-3 mb-8">
                          <div className="p-2 bg-primary/10 text-primary rounded-lg">
                            <Plus size={24} />
                          </div>
                          <h3 className="text-xl font-headline font-bold text-secondary">MCP Tools</h3>
                        </div>
                        <div className="space-y-4">
                          <MCPTool 
                            name="Local Forest DB"
                            status="Active Connector"
                            icon="database"
                            active
                          />
                          <MCPTool 
                            name="Weather Patterns"
                            status="Syncing..."
                            icon="cloud"
                          />
                          <MCPTool 
                            name="Root Terminal"
                            status="Paused"
                            icon="terminal"
                            paused
                          />
                        </div>
                        <button className="w-full mt-8 py-4 border-2 border-dashed border-secondary/20 rounded-2xl text-secondary font-bold text-sm hover:bg-surface-container-highest hover:border-secondary/40 transition-all flex items-center justify-center gap-2">
                          <Plus size={18} />
                          Connect New MCP
                        </button>
                      </div>
                    </div>

                    {/* Insight Card Section */}
                    <InsightCard />

                    {/* Harmony Rating Section */}
                    <HarmonyRating />
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab !== 'skills' && activeTab !== 'chat' && (
              <motion.div
                key="placeholder"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="h-full flex flex-col items-center justify-center text-secondary/40"
              >
                <div className="w-24 h-24 rounded-full bg-surface-container flex items-center justify-center mb-4">
                  {activeTab === 'settings' ? <Settings size={48} /> : 
                   activeTab === 'provider' ? <Cpu size={48} /> :
                   activeTab === 'platform' ? <Globe size={48} /> :
                   <MessageSquare size={48} />}
                </div>
                <h3 className="text-2xl font-headline font-medium">Coming Soon</h3>
                <p className="font-body italic">This part of the conservatory is still growing.</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}
