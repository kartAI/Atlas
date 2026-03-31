import { useState, useRef, useEffect, useCallback } from 'react';
import { ArrowUp, Paperclip, FileText, X, Plus } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { AuthModal } from './AuthModal';
import { ChatHistory } from './ChatHistory';
import {
  apiFetch,
  clearActiveChatId,
  clearToken,
  getActiveChatId,
  getToken,
  setActiveChatId,
} from '../utils/auth';

export function ChatInterface({ externalUser, onUserChange }) {
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
          await loadChatMessages(savedChatId);
          setActiveChatIdState(savedChatId);
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
      if (!res.ok) return;
      const data = await res.json();
      const loaded = (data.messages || []).map(m => ({
        role: m.role,
        text: m.content || '',
        attachments: [],
      }));
      setMessages(loaded);
    } catch {
      // Silently ignore.
    }
  }

  function handleAuthSuccess(userData) {
    setUser(userData);
    setActiveChatIdState(null);
    setMessages([]);
    setChats([]);
    setChatsLoaded(false);
    onUserChange?.(userData);
  }

  async function handleLogout() {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch {
      // Best-effort logout.
    }
    clearToken();
    clearActiveChatId();
    setUser(null);
    setActiveChatIdState(null);
    setMessages([]);
    setChats([]);
    setChatsLoaded(false);
    setActiveTab('chat');
    onUserChange?.(null);
  }

  async function handleNewChat() {
    setActiveChatIdState(null);
    setActiveChatId(null);
    setMessages([]);
    setInput('');
    setAttachments([]);
    setActiveTab('chat');
  }

  async function handleContinueChat(chatId) {
    await loadChatMessages(chatId);
    setActiveChatIdState(chatId);
    setActiveChatId(chatId);
    setActiveTab('chat');
  }

  async function handleDeleteChat(chatId) {
    try {
      const res = await apiFetch(`/api/chats/${chatId}`, { method: 'DELETE' });
      if (!res.ok) return;
    } catch {
      return;
    }
    if (chatId === activeChatId) {
      setActiveChatIdState(null);
      setActiveChatId(null);
      setMessages([]);
    }
    setChats(prev => prev.filter(c => c.id !== chatId));
  }

  async function handleDeleteManyChats(chatIds) {
    // Fire deletions in parallel; ignore individual failures gracefully.
    await Promise.allSettled(
      chatIds.map(id => apiFetch(`/api/chats/${id}`, { method: 'DELETE' }))
    );
    if (chatIds.includes(activeChatId)) {
      setActiveChatIdState(null);
      setActiveChatId(null);
      setMessages([]);
    }
    setChats(prev => prev.filter(c => !chatIds.includes(c.id)));
  }

  // Send message

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed && attachments.length === 0) return;
    if (isLoading) return;

    const userMessage = { role: 'user', text: trimmed, attachments: [...attachments] };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setAttachments([]);
    setIsLoading(true);

    try {
      const res = await apiFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: trimmed,
          chat_id: activeChatId || undefined,
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

      if (!activeChatId && data.chat_id) {
        setActiveChatIdState(data.chat_id);
        setActiveChatId(data.chat_id);
        setChatsLoaded(false); // Invalidate so history refreshes next open.
      }

      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: data.reply, attachments: [] },
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
                const hasText = !!msg.text;

                return (
                  <div key={i} className={`message-wrapper message-wrapper--${msg.role}`}>
                    {(images.length > 0 || files.length > 0) && (
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
                      </div>
                    )}
                    {hasText && (
                      <div className={`chat-bubble chat-bubble--${msg.role}`}>
                        {msg.role === 'assistant'
                          ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
                          : msg.text}
                      </div>
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

          {attachments.length > 0 && (
            <div className="attachment-preview-strip">
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