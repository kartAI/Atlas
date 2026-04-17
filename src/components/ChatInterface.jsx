import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react';
import { ArrowUp, Paperclip, FileText, X, Plus, Wrench } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { AuthModal } from './AuthModal';
import { ChatHistory } from './ChatHistory';
import { TurnUsage, MonthlyUsageBar, InputAreaUsageBar } from './UsageDisplay';
import {
  apiFetch,
  clearActiveChatId,
  clearToken,
  getActiveChatId,
  getToken,
  setActiveChatId,
} from '../utils/auth';

export function ChatInterface({ externalUser, onUserChange, drawnLayers = [], onLayerCreated, onSetDrawnLayers, selectedTools = [], onClearSelectedTools, onRemoveTool }) {
  // Auth state
  const [user, setUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  // Tab state
  const [activeTab, setActiveTab] = useState('chat');

  // Chat state
  const [activeChatId, setActiveChatIdState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [chats, setChats] = useState([]);
  const [chatsLoaded, setChatsLoaded] = useState(false);

  // Input state
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const bottomRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  const MAX_TEXTAREA_HEIGHT = 250; // ~5 rows

  // Auto-resize textarea as user types
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const newHeight = Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT);
    el.style.height = `${newHeight}px`;
    el.style.overflowY = el.scrollHeight > MAX_TEXTAREA_HEIGHT ? 'auto' : 'hidden';
    el.style.borderRadius = newHeight > 44 ? '14px' : '999px';
  }, [input]);

  // Usage tracking state
  const [usageSession, setUsageSession] = useState(null);
  const [usageMonthly, setUsageMonthly] = useState(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // External logout signal (e.g. header logout button)
  useEffect(() => {
    if (externalUser === null && user !== null) {
      setUser(null);
      setActiveChatIdState(null);
      setMessages([]);
      setChats([]);
      setChatsLoaded(false);
      setActiveTab('chat');
      setInput('');
      setAttachments([]);
      setUsageSession(null);
      setUsageMonthly(null);
      onSetDrawnLayers?.([]);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalUser]);

  // On mount: verify token, restore last active chat
  useEffect(() => {
    async function init() {
      const token = getToken();
      if (!token) {
        setAuthChecked(true);
        return;
      }
      try {
        const res = await apiFetch('/api/auth/me');
        if (!res.ok) {
          clearToken();
          clearActiveChatId();
          setAuthChecked(true);
          return;
        }
        const data = await res.json();
        const userData = { user_id: data.user_id, email: data.email };
        setUser(userData);
        onUserChange?.(userData);

        const savedChatId = getActiveChatId();
        if (savedChatId) {
          const loaded = await loadChatMessages(savedChatId);
          if (loaded) {
            setActiveChatIdState(savedChatId);
            await loadChatLayers(savedChatId);
          } else {
            clearActiveChatId();
          }
        }
      } catch {
        clearToken();
        clearActiveChatId();
      } finally {
        setAuthChecked(true);
      }
    }
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load chat list when history tab opens
  useEffect(() => {
    if (activeTab === 'history' && user && !chatsLoaded) {
      refreshChatList();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, user]);

  // Helpers

  const refreshChatList = useCallback(async () => {
    try {
      const res = await apiFetch('/api/chats');
      if (res.ok) {
        const data = await res.json();
        setChats(data.chats || []);
        setChatsLoaded(true);
      }
    } catch {
      // Silently ignore; list stays stale.
    }
  }, []);

  async function loadChatMessages(chatId) {
    try {
      const res = await apiFetch(`/api/chats/${chatId}/messages`);
      if (!res.ok) return false;
      const data = await res.json();
      const loaded = (data.messages || []).map(m => ({
        role: m.role,
        text: m.content || '',
        attachments: [],
      }));
      setMessages(loaded);
      return true;
    } catch {
      // Silently ignore.
      return false;
    }
  }

  async function loadChatLayers(chatId) {
    try {
      const res = await apiFetch(`/api/chats/${chatId}/layers`);
      if (!res.ok) return;
      const data = await res.json();
      const loaded = (data.layers || []).map(l => ({
        id: l.layer_id,
        name: l.name,
        shape: l.shape,
        visible: l.visible,
        geoJson: l.geojson,
      }));
      onSetDrawnLayers?.(loaded);
    } catch {
      // Non-critical; layers stay empty.
    }
  }

  function handleAuthSuccess(userData) {
    setUser(userData);
    setActiveChatIdState(null);
    setMessages([]);
    setChats([]);
    setChatsLoaded(false);
    setUsageSession(null);
    setUsageMonthly(null);
    onUserChange?.(userData);
  }

  async function handleNewChat() {
    setActiveChatIdState(null);
    setActiveChatId(null);
    setMessages([]);
    setInput('');
    setAttachments([]);
    setActiveTab('chat');
    setUsageSession(null);
    setUsageMonthly(null);
    onSetDrawnLayers?.([]);
  }

  async function handleContinueChat(chatId) {
    const loaded = await loadChatMessages(chatId);
    if (!loaded) return;
    setActiveChatIdState(chatId);
    setActiveChatId(chatId);
    setActiveTab('chat');
    // Load persisted layers for this chat.
    await loadChatLayers(chatId);
    // Fetch current usage for this chat if a tracker exists on the backend.
    setUsageSession(null);
    setUsageMonthly(null);
    try {
      const res = await apiFetch(`/api/usage?chat_id=${chatId}`);
      if (res.ok) {
        const d = await res.json();
        if (d.usage) {
          setUsageSession(d.usage.session || null);
          setUsageMonthly(d.usage.monthly || null);
        }
      }
    } catch {
      // Non-critical; usage will repopulate on next message.
    }
  }

  async function handleDeleteManyChats(chatIds) {
    const results = await Promise.allSettled(
      chatIds.map(id => apiFetch(`/api/chats/${id}`, { method: 'DELETE' }))
    );
    const deletedIds = results.flatMap((result, index) => {
      if (result.status === 'fulfilled' && result.value.ok) {
        return chatIds[index];
      }
      return [];
    });

    if (deletedIds.includes(activeChatId)) {
      setActiveChatIdState(null);
      setActiveChatId(null);
      setMessages([]);
      setUsageSession(null);
      setUsageMonthly(null);
    }

    if (deletedIds.length > 0) {
      setChats(prev => prev.filter(c => !deletedIds.includes(c.id)));
    }
  }

  // Send message

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed && attachments.length === 0) return;
    if (isLoading) return;

    const sentTools = [...selectedTools];
    const userMessage = { role: 'user', text: trimmed, attachments: [...attachments], tools: sentTools };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setAttachments([]);
    onClearSelectedTools?.();
    setIsLoading(true);

    try {
      const res = await apiFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: trimmed,
          chat_id: activeChatId || undefined,
          map_context: drawnLayers,
          tool_hints: sentTools.map(t => t.mcpTool),
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setMessages(prev => [
          ...prev,
          { role: 'assistant', text: data.error || 'En feil oppstod.', attachments: [] },
        ]);
        return;
      }

      if (data.map_actions?.length && onLayerCreated) {
        data.map_actions.forEach(action => {
          const geojson = action.geojson;
          const shape = geojson?.type === 'FeatureCollection'
            ? 'FeatureCollection'
            : (geojson?.geometry?.type || 'Feature');
          onLayerCreated({
            id: action.layer_id || `drawn-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            name: action.layer_name,
            shape,
            geoJson: geojson,
            visible: true,
          }, { persisted: true });
        });
      }

      if (!activeChatId && data.chat_id) {
        setActiveChatIdState(data.chat_id);
        setActiveChatId(data.chat_id);
        setChatsLoaded(false); // Invalidate so history refreshes next open.

        // Bulk-persist any pre-existing drawn layers to the newly created chat.
        const persistable = drawnLayers.filter(l => l.id && l.geoJson);
        if (persistable.length > 0) {
          apiFetch(`/api/chats/${data.chat_id}/layers/bulk`, {
            method: 'POST',
            body: JSON.stringify({
              layers: persistable.map(l => ({
                layer_id: l.id,
                name: l.name || 'Untitled layer',
                shape: l.shape || 'Feature',
                visible: l.visible !== false,
                geojson: l.geoJson,
              })),
            }),
          }).catch(() => { /* fire-and-forget */ });
        }
      }

      // Update usage state from the response.
      if (data.usage) {
        setUsageSession(data.usage.session || null);
        setUsageMonthly(data.usage.monthly || null);
      }

      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          text: data.reply,
          attachments: [],
          turnUsage: data.usage?.turn || null,
        },
      ]);
    } catch {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: 'Kunne ikke kontakte serveren.', attachments: [] },
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    const newAttachments = files.map(file => {
      const isImage = file.type.startsWith('image/');
      return {
        id: crypto.randomUUID(),
        file,
        name: file.name,
        size: file.size,
        type: file.type,
        preview: isImage ? URL.createObjectURL(file) : null,
      };
    });
    setAttachments(prev => [...prev, ...newAttachments]);
    e.target.value = '';
  }

  function removeAttachment(id) {
    setAttachments(prev => {
      const item = prev.find(a => a.id === id);
      if (item?.preview) URL.revokeObjectURL(item.preview);
      return prev.filter(a => a.id !== id);
    });
  }

  // Render

  if (!authChecked) {
    return (
      <div className="chat-interface">
        <div className="chat-loading">Laster…</div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      {/* Auth overlay */}
      {!user && <AuthModal onSuccess={handleAuthSuccess} />}

      {/* Tab bar */}
      <div className="chat-tabs">
        <button
          className={`chat-tab${activeTab === 'chat' ? ' chat-tab--active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          Samtale
        </button>

        <button
          className={`chat-tab${activeTab === 'history' ? ' chat-tab--active' : ''}`}
          onClick={() => {
            setActiveTab('history');
            if (user && !chatsLoaded) refreshChatList();
          }}
        >
          Historikk
        </button>

        {user && (
          <button
            className="chat-tab-new-btn"
            title="Ny samtale"
            onClick={handleNewChat}
            aria-label="Ny samtale"
          >
            <Plus size={14} />
            <span>Ny samtale</span>
          </button>
        )}
      </div>

      {/* Samtale tab */}
      {activeTab === 'chat' && (
        <>
          <div className="chat-messages">
            {messages.length === 0 ? (
              <p className="chat-empty">Start samtalen…</p>
            ) : (
              messages.map((msg, i) => {
                const images = msg.attachments?.filter(att => att.preview) || [];
                const files  = msg.attachments?.filter(att => !att.preview) || [];
                const tools  = msg.tools || [];
                const hasText = !!msg.text;

                return (
                  <div key={i} className={`message-wrapper message-wrapper--${msg.role}`}>
                    {(images.length > 0 || files.length > 0 || tools.length > 0) && (
                      <div className="message-attachments-wrapper">
                        {images.length > 0 && (
                          <div className={`message-image-attachments ${hasText || images.length > 1 ? 'message-image-attachments--preview' : ''}`}>
                            {images.map(att => (
                              <div key={att.id} className="attachment-image">
                                <img src={att.preview} alt={att.name} />
                              </div>
                            ))}
                          </div>
                        )}
                        {files.length > 0 && (
                          <div className={`message-file-attachments ${hasText || files.length > 1 ? 'message-file-attachments--preview' : ''}`}>
                            {files.map(att => (
                              <div key={att.id} className="attachment-card">
                                <div className="attachment-file-icon"><FileText size={26} /></div>
                                <span className="attachment-file-name">{att.name}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {tools.length > 0 && (
                          <div className="message-tool-attachments">
                            {tools.map(tool => (
                              <div key={tool.name} className="tool-chip tool-chip--sent">
                                <Wrench size={13} />
                                <span>{tool.name}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                    {hasText && (
                      <div className={`chat-bubble chat-bubble--${msg.role}`}>
                        {msg.role === 'assistant'
                          ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
                          : msg.text}
                      </div>
                    )}
                    {msg.role === 'assistant' && msg.turnUsage && (
                      <TurnUsage usage={msg.turnUsage} />
                    )}
                  </div>
                );
              })
            )}

            {isLoading && (
              <div className="message-wrapper message-wrapper--assistant">
                <div className="chat-bubble chat-bubble--assistant chat-bubble--typing">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {(attachments.length > 0 || selectedTools.length > 0) && (
            <div className="attachment-preview-strip">
              {selectedTools.map(tool => {
                const Icon = tool.icon;
                return (
                  <div key={`tool-${tool.name}`} className="attachment-card attachment-card--tool">
                    <button className="attachment-remove" onClick={() => onRemoveTool?.(tool)}>
                      <X size={14} />
                    </button>
                    <div className="attachment-tool-icon">
                      {typeof Icon === 'function' ? <Icon size={26} strokeWidth={1.8} /> : <Wrench size={26} />}
                    </div>
                    <div className="attachment-info">
                      <span className="attachment-name">{tool.name}</span>
                      <span className="attachment-size">Verktøy</span>
                    </div>
                  </div>
                );
              })}
              {attachments.map(att => (
                <div key={att.id} className="attachment-card">
                  <button className="attachment-remove" onClick={() => removeAttachment(att.id)}>
                    <X size={14} />
                  </button>
                  {att.preview
                    ? <img src={att.preview} alt={att.name} className="attachment-thumb" />
                    : <div className="attachment-file-icon"><FileText size={28} /></div>}
                  <div className="attachment-info">
                    <span className="attachment-name">{att.name}</span>
                    <span className="attachment-size">{(att.size / 1024).toFixed(1)} KB</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Unified session + monthly usage strip above input */}
          <InputAreaUsageBar monthly={usageMonthly} session={usageSession} />

          <div className="chat-input-area">
            <div className="paperclip">
              <button onClick={() => fileInputRef.current?.click()}><Paperclip size={18} /></button>
              <input
                type="file"
                style={{ display: 'none' }}
                ref={fileInputRef}
                accept="image/*, .pdf, .jpg, .jpeg, .png, .doc, .txt"
                multiple
                onChange={handleFileSelect}
              />
            </div>
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Skriv en melding…"
              disabled={isLoading || !user}
            />
            <button onClick={handleSend} disabled={isLoading || !user}>
              <ArrowUp size={18} />
            </button>
          </div>
        </>
      )}

      {activeTab === 'history' && (
        <ChatHistory
          chats={chats}
          activeChatId={activeChatId}
          onContinue={handleContinueChat}
          onDeleteMany={handleDeleteManyChats}
        />
      )}
    </div>
  );
}
