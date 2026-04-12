import React, { useEffect, useRef, useState } from 'react';
import { Send, User, Leaf, Sparkles, Paperclip, Smile } from 'lucide-react';
import { cn } from '@/src/lib/utils';
import { motion, AnimatePresence } from 'motion/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface BrainSnapshot {
  self_cognition: string;
  world_model: string;
  stable_identity: string;
  relationship_style: string;
  relationship_stage: string;
  proactivity_policy: string;
  emotional_context: string;
  user_emotional_state: string;
  agent_continuity_state: string;
  support_policy: string;
  session_adaptations: string;
  task_experience: string;
  tool_list: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  brain?: BrainSnapshot;
}

interface ChatMessageEvent {
  type: string;
  content: string;
  metadata?: {
    brain?: BrainSnapshot;
    streamed?: boolean;
  };
}

interface ChatApiResponse {
  reply: string;
  session_id: string;
  user_id: string;
  status: string;
  brain?: BrainSnapshot | null;
}

const BRAIN_SECTIONS: Array<{ key: keyof BrainSnapshot; label: string }> = [
  { key: 'self_cognition', label: 'Self Cognition' },
  { key: 'world_model', label: 'World Model' },
  { key: 'stable_identity', label: 'Stable Identity' },
  { key: 'relationship_style', label: 'Relationship Style' },
  { key: 'relationship_stage', label: 'Relationship Stage' },
  { key: 'proactivity_policy', label: 'Proactivity Policy' },
  { key: 'emotional_context', label: 'Emotional Context' },
  { key: 'user_emotional_state', label: 'User Emotional State' },
  { key: 'agent_continuity_state', label: 'Agent Continuity State' },
  { key: 'support_policy', label: 'Support Policy' },
  { key: 'session_adaptations', label: 'Session Adaptation' },
  { key: 'task_experience', label: 'Task Experience' },
  { key: 'tool_list', label: 'Available Tools' },
];

export const ChatView: React.FC = () => {
  const userId = 'user-1';
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: "Greetings, traveler of the digital woods. I am your Sylvan companion. How shall we nurture our conversation today?",
      timestamp: new Date(),
    }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [sessionId] = useState(() => crypto.randomUUID());
  const [isReceiving, setIsReceiving] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const latestBrain = [...messages].reverse().find(message => message.role === 'assistant' && message.brain)?.brain;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isReceiving]);

  useEffect(() => {
    const eventSource = new EventSource(`/api/chat/stream?session_id=${sessionId}&user_id=${userId}`);

    eventSource.addEventListener('delta', (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.delta) {
          setMessages(prev => {
            const newMessages = [...prev];
            const lastIndex = newMessages.length - 1;
            const lastMsg = newMessages[lastIndex];
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.id === 'streaming_current') {
              newMessages[lastIndex] = {
                ...lastMsg,
                content: lastMsg.content + data.delta
              };
            } else {
              newMessages.push({
                id: 'streaming_current',
                role: 'assistant',
                content: data.delta,
                timestamp: new Date()
              });
            }
            return newMessages;
          });
        }
      } catch (err) {
        console.error('Error parsing delta', err);
      }
    });

    eventSource.addEventListener('message', (event) => {
      try {
        const data: ChatMessageEvent = JSON.parse(event.data);
        if (data.type !== 'text' || !data.content) {
          return;
        }
        setMessages(prev => {
          const newMessages = [...prev];
          const lastIndex = newMessages.length - 1;
          const lastMsg = newMessages[lastIndex];
          if (lastMsg && lastMsg.role === 'assistant' && lastMsg.id === 'streaming_current') {
            newMessages[lastIndex] = {
              ...lastMsg,
              id: Date.now().toString(),
              content: data.content,
              brain: data.metadata?.brain
            };
          } else {
            newMessages.push({
              id: Date.now().toString(),
              role: 'assistant',
              content: data.content,
              timestamp: new Date(),
              brain: data.metadata?.brain
            });
          }
          return newMessages;
        });
      } catch (err) {
        console.error('Error parsing message event', err);
      }
    });

    eventSource.addEventListener('done', () => {
      setIsReceiving(false);
      setMessages(prev => {
        const newMessages = [...prev];
        const lastMsg = newMessages[newMessages.length - 1];
        if (lastMsg && lastMsg.id === 'streaming_current') {
          lastMsg.id = Date.now().toString();
        }
        return newMessages;
      });
    });

    eventSource.onerror = (err) => {
      console.error("SSE Error", err);
    };

    return () => {
      eventSource.close();
    };
  }, [sessionId, userId]);

  const handleSend = async () => {
    if (!inputValue.trim() || isReceiving) return;

    const userText = inputValue;
    const newMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: userText,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, newMessage]);
    setInputValue('');
    setIsReceiving(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: userText,
          session_id: sessionId,
          user_id: userId,
          include_trace: false
        })
      });
      if (!response.ok) {
        throw new Error(`Chat request failed with status ${response.status}`);
      }
      const data: ChatApiResponse = await response.json();
      if (data.brain) {
        setMessages(prev => {
          const newMessages = [...prev];
          const lastIndex = newMessages.length - 1;
          const lastMsg = newMessages[lastIndex];
          if (lastMsg && lastMsg.role === 'assistant') {
            newMessages[lastIndex] = {
              ...lastMsg,
              brain: data.brain ?? undefined
            };
          }
          return newMessages;
        });
      }
    } catch (e) {
      console.error(e);
      setIsReceiving(false);
    }
  };

  return (
    <div className="h-full bg-surface-container-low md:rounded-[2.5rem] md:tactile-card relative overflow-hidden">
      <div className="grain-texture absolute inset-0 pointer-events-none" />

      <div className="relative z-10 flex h-full flex-col xl:flex-row">
        <div className="flex min-h-0 flex-1 flex-col xl:border-r xl:border-surface-container-highest">
          <header className="flex-shrink-0 px-4 md:px-8 py-4 md:py-6 border-b border-surface-container-highest flex justify-between items-center bg-surface/50 backdrop-blur-sm">
            <div className="flex items-center gap-3 md:gap-4">
              <div className="w-10 h-10 md:w-12 md:h-12 rounded-xl bg-primary/10 flex items-center justify-center text-primary shadow-inner">
                <Leaf size={20} className="md:w-6 md:h-6" />
              </div>
              <div>
                <h3 className="text-lg md:text-xl font-headline font-bold text-secondary">Sylvan Dialogue</h3>
                <p className="text-[10px] md:text-xs text-secondary/60 font-label flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                  Connected to Ancient Wisdom Module
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button className="p-2 text-secondary/60 hover:text-secondary hover:bg-surface-container transition-colors rounded-lg">
                <Sparkles size={20} />
              </button>
            </div>
          </header>

          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto p-4 md:p-8 space-y-4 md:space-y-6 scroll-smooth"
          >
            <AnimatePresence initial={false}>
              {messages.map((msg) => (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  className={cn(
                    "flex w-full",
                    msg.role === 'user' ? "justify-end" : "justify-start"
                  )}
                >
                  <div className={cn(
                    "flex gap-2 md:gap-4 max-w-[90%] md:max-w-[80%]",
                    msg.role === 'user' ? "flex-row-reverse" : "flex-row"
                  )}>
                    <div className={cn(
                      "w-8 h-8 md:w-10 md:h-10 rounded-xl flex-shrink-0 flex items-center justify-center shadow-sm",
                      msg.role === 'user' ? "bg-secondary text-on-secondary" : "bg-primary text-on-primary"
                    )}>
                      {msg.role === 'user' ? <User size={16} className="md:w-5 md:h-5" /> : <Leaf size={16} className="md:w-5 md:h-5" />}
                    </div>
                    <div className={cn(
                      "p-3 md:p-5 rounded-2xl shadow-sm relative",
                      msg.role === 'user'
                        ? "bg-surface-container-highest text-on-surface rounded-tr-none"
                        : "bg-surface text-on-surface rounded-tl-none border border-surface-container-high"
                    )}>
                      <div className={cn(
                        "prose md:prose-lg max-w-none break-words",
                        msg.role === 'user' ? "prose-invert prose-p:text-on-surface prose-headings:text-on-surface text-on-surface prose-a:text-on-surface" : "prose-p:text-on-surface prose-headings:text-on-surface text-on-surface prose-a:text-primary"
                      )}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                      <span className="text-[10px] uppercase tracking-widest opacity-40 mt-3 block font-label">
                        {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          <footer className="flex-shrink-0 p-4 md:p-8 bg-surface/50 backdrop-blur-sm border-t border-surface-container-highest">
            <div className="max-w-4xl mx-auto relative">
              <div className="bg-surface rounded-2xl recessed-field p-1 md:p-2 flex items-end gap-1 md:gap-2">
                <button className="p-2 md:p-3 text-secondary/40 hover:text-primary transition-colors">
                  <Paperclip size={18} className="md:w-5 md:h-5" />
                </button>
                <textarea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="Whisper your thoughts..."
                  className="flex-1 bg-transparent border-none focus:ring-0 font-body text-base md:text-lg text-on-surface py-2 md:py-3 px-1 md:px-2 resize-none min-h-[40px] max-h-[150px] outline-none"
                  rows={1}
                />
                <div className="flex items-center gap-0.5 md:gap-1 pb-1 pr-1">
                  <button className="hidden sm:block p-2 md:p-3 text-secondary/40 hover:text-primary transition-colors">
                    <Smile size={18} className="md:w-5 md:h-5" />
                  </button>
                  <button
                    onClick={handleSend}
                    disabled={!inputValue.trim()}
                    className={cn(
                      "p-2 md:p-3 rounded-xl transition-all duration-300 shadow-md",
                      inputValue.trim()
                        ? "bg-primary text-on-primary hover:scale-105 active:scale-95"
                        : "bg-surface-container-highest text-secondary/20 cursor-not-allowed"
                    )}
                  >
                    <Send size={18} className="md:w-5 md:h-5" />
                  </button>
                </div>
              </div>
              <p className="hidden md:block text-[10px] text-center mt-3 text-secondary/40 uppercase tracking-widest font-bold">
                Press Enter to send 鈥?Shift + Enter for new line
              </p>
            </div>
          </footer>
        </div>

        <aside className="w-full xl:w-[420px] border-t xl:border-t-0 border-surface-container-highest bg-surface/70 backdrop-blur-sm flex min-h-0 flex-col">
          <div className="px-4 md:px-6 py-4 border-b border-surface-container-highest">
            <p className="text-[10px] uppercase tracking-[0.35em] text-secondary/50 font-bold">Debug Brain</p>
            <h4 className="mt-2 text-xl font-headline font-bold text-secondary">Prompt Snapshot</h4>
            <p className="mt-1 text-sm text-secondary/70 font-body">
              Shows the latest assistant brain fields returned by the backend.
            </p>
          </div>

          <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
            {latestBrain ? (
              BRAIN_SECTIONS.map(section => (
                <section
                  key={section.key}
                  className="rounded-2xl border border-surface-container-high bg-surface-container-low/80 p-4 shadow-sm"
                >
                  <h5 className="text-xs uppercase tracking-[0.25em] text-secondary/60 font-bold">
                    {section.label}
                  </h5>
                  <pre className="mt-3 whitespace-pre-wrap break-words text-[13px] leading-6 text-on-surface font-label">
                    {latestBrain[section.key]}
                  </pre>
                </section>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-surface-container-highest bg-surface-container-low/50 p-6 text-sm text-secondary/70 font-body">
                No brain snapshot yet. Send a message and the latest assistant reply will populate this panel.
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
};
