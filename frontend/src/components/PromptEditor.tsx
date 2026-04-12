import React, { useState, useEffect } from 'react';
import { Info, Save, RotateCcw, Check, Loader2 } from 'lucide-react';

interface PromptTemplate {
  key: string;
  content: string;
}

export const PromptEditor: React.FC = () => {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [defaults, setDefaults] = useState<PromptTemplate[]>([]);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editContent, setEditContent] = useState<string>('');
  const [originalContent, setOriginalContent] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [promptsRes, defaultsRes] = await Promise.all([
        fetch('/api/prompts'),
        fetch('/api/prompts/defaults'),
      ]);
      if (!promptsRes.ok) throw new Error('Failed to load prompts');
      if (!defaultsRes.ok) throw new Error('Failed to load defaults');

      const promptsData = await promptsRes.json();
      const defaultsData = await defaultsRes.json();

      setPrompts(promptsData.items || []);
      setDefaults(defaultsData.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleEdit = (prompt: PromptTemplate) => {
    setEditingKey(prompt.key);
    setEditContent(prompt.content);
    setOriginalContent(prompt.content);
    setSaved(false);
    setResetSuccess(false);
  };

  const handleCancel = () => {
    setEditingKey(null);
    setEditContent('');
    setOriginalContent('');
    setSaved(false);
    setResetSuccess(false);
  };

  const handleSave = async (key: string) => {
    if (editContent.trim() === originalContent) {
      handleCancel();
      return;
    }

    try {
      setSaving(true);
      setError(null);
      const response = await fetch(`/api/prompts/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContent }),
      });
      if (!response.ok) throw new Error('Failed to save prompt');

      const data = await response.json();
      setPrompts(prev =>
        prev.map(p => (p.key === key ? { ...p, content: data.content } : p))
      );
      setSaved(true);
      setEditingKey(null);
      setEditContent('');
      setOriginalContent('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setSaving(false);
    }
  };

  const handleResetToDefault = async (key: string) => {
    try {
      setResetting(true);
      setError(null);
      const response = await fetch(`/api/prompts/${key}/reset`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to reset prompt');

      const data = await response.json();
      setPrompts(prev =>
        prev.map(p => (p.key === key ? { ...p, content: data.content } : p))
      );
      if (editingKey === key) {
        setEditContent(data.content);
        setOriginalContent(data.content);
      }
      setResetSuccess(true);
      setTimeout(() => setResetSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setResetting(false);
    }
  };

  const isModified = (prompt: PromptTemplate) => {
    const defaultPrompt = defaults.find(d => d.key === prompt.key);
    return defaultPrompt && prompt.content !== defaultPrompt.content;
  };

  if (loading) {
    return (
      <div className="bg-surface-container-highest rounded-[2.5rem] p-8 tactile-card relative overflow-hidden flex items-center justify-center min-h-[300px]">
        <Loader2 className="w-8 h-8 text-secondary animate-spin" />
      </div>
    );
  }

  return (
    <div className="bg-surface-container-highest rounded-[2.5rem] p-8 tactile-card relative overflow-hidden">
      <div className="grain-texture absolute inset-0 pointer-events-none" />
      <div className="relative z-10">
        <div className="flex justify-between items-center mb-8">
          <h3 className="text-2xl font-headline font-bold text-secondary">Core Prompt Editor</h3>
          <div className="flex gap-2 items-center">
            <Info size={20} className="text-secondary cursor-help" />
            {error && <span className="text-red-400 text-sm">{error}</span>}
            {resetSuccess && (
              <span className="text-green-400 text-sm flex items-center gap-1">
                <Check size={14} />
                Reset to default
              </span>
            )}
          </div>
        </div>

        <div className="space-y-6">
          {prompts.map((prompt) => (
            <div key={prompt.key} className="bg-surface rounded-[1.5rem] p-6 recessed-field">
              <div className="flex justify-between items-center mb-4">
                <div className="flex items-center gap-3">
                  <label className="text-[10px] font-black uppercase tracking-widest text-secondary/60">
                    {prompt.key.replace(/_/g, ' ')}
                  </label>
                  {isModified(prompt) && (
                    <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-amber-500/20 text-amber-400">
                      Modified
                    </span>
                  )}
                </div>
                {editingKey === prompt.key ? (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleResetToDefault(prompt.key)}
                      disabled={resetting}
                      className="px-3 py-1.5 text-xs font-bold rounded-lg border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 transition-colors flex items-center gap-1 disabled:opacity-50"
                      title="Reset to default"
                    >
                      {resetting ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                      Reset
                    </button>
                    <button
                      onClick={handleCancel}
                      className="px-3 py-1.5 text-xs font-bold rounded-lg border border-secondary/20 text-secondary hover:bg-surface-container transition-colors flex items-center gap-1"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => handleSave(prompt.key)}
                      disabled={saving}
                      className="px-3 py-1.5 text-xs font-bold rounded-lg bg-primary text-on-primary shadow-md hover:shadow-lg transition-all flex items-center gap-1 disabled:opacity-50"
                    >
                      {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                      Save
                    </button>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    {isModified(prompt) && (
                      <button
                        onClick={() => handleResetToDefault(prompt.key)}
                        disabled={resetting}
                        className="px-3 py-1.5 text-xs font-bold rounded-lg border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 transition-colors flex items-center gap-1 disabled:opacity-50"
                        title="Reset to default"
                      >
                        {resetting ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                        Reset
                      </button>
                    )}
                    <button
                      onClick={() => handleEdit(prompt)}
                      className="px-3 py-1.5 text-xs font-bold rounded-lg border border-primary/30 text-primary hover:bg-primary/10 transition-colors"
                    >
                      Edit
                    </button>
                  </div>
                )}
              </div>

              {editingKey === prompt.key ? (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full bg-transparent border border-primary/30 rounded-xl p-4 focus:ring-1 focus:ring-primary font-body text-sm text-on-surface leading-relaxed min-h-[200px] resize-y outline-none"
                  autoFocus
                />
              ) : (
                <div className="text-sm font-body text-on-surface/80 leading-relaxed whitespace-pre-wrap max-h-[200px] overflow-y-auto">
                  {prompt.content}
                </div>
              )}

              {saved && editingKey === null && (
                <div className="mt-3 flex items-center gap-1 text-green-400 text-xs font-bold">
                  <Check size={14} />
                  Saved successfully
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};