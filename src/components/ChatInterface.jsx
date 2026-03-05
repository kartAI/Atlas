import { useState, useRef, useEffect } from 'react';
import { Send, Paperclip, FileText, X } from 'lucide-react';

export function ChatInterface() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const bottomRef = useRef(null);
  const [attachments, setAttachments] = useState([]);
  const fileInputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  function handleSend() {
    const trimmed = input.trim();
    if (!trimmed) return;
    setMessages((prev) => [...prev, { role: 'user', text: trimmed, attachments: [...attachments] }]);
    setInput('');
    setAttachments([]);
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
  
    const newAttachments = files.map((file) =>{
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
    setAttachments((prev) => [...prev, ...newAttachments]);
    e.target.value = ''; // Accept re-choice of same file
  }

  function removeAttachment(id) {
    setAttachments((prev) => {
      const item = prev.find((a) => a.id === id);
      if (item?.preview) URL.revokeObjectURL(item.preview);
      return prev.filter((a) => a.id !== id);
    });
  }

  return (
    <div className="chat-interface">
      <div className="chat-messages">
        {messages.length === 0 ? (
          <p className="chat-empty">Start samtalen...</p>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`chat-bubble chat-bubble--${msg.role}`}>
              {msg.text}
              {msg.attachments && msg.attachments.length > 0 && (
                <div className="message-attachments">
                  {msg.attachments.map((att) => (
                    <div key={att.id} className="attachment-card">
                      {att.preview ? (
                        <img src={att.preview} alt={att.name} className="attachment-thumb" />
                      ) : (
                        <div className="attachment-file-icon">
                          <FileText size={28} />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

     {attachments.length > 0 && (
  <div className="attachment-preview-strip">
    {attachments.map((att) => (
      <div key={att.id} className="attachment-card">

        {/* X-button in the top corner */}
        <button className="attachment-remove" onClick={() => removeAttachment(att.id)}>
          <X size={14} />
        </button>

        {/* Thumbnails/Icons for file preview */}
        {att.preview
          ? <img src={att.preview} alt={att.name} className="attachment-thumb" />
          : <div className="attachment-file-icon"><FileText size={28} /></div>
        }

        {/* Filesize */}
        <div className="attachment-info">
          <span className="attachment-name">{att.name}</span>
          <span className="attachment-size">{(att.size / 1024).toFixed(1)} KB</span>
        </div>

      </div>
    ))}
  </div>
)}

      <div className="chat-input-area">
        <div className="Paperclip">
        <button onClick={() => fileInputRef.current.click()}><Paperclip size={18} /></button>
        <input 
          type="file" 
          style={{ display: 'none' }} 
          id="file-upload" ref={fileInputRef} 
          accept="image/*, .pdf, .jpg, .jpeg, .png, .doc, .txt" 
          multiple
          onChange={handleFileSelect}
       />
        </div>
        <textarea
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Skriv en melding..."
        />
        <button onClick={handleSend}><Send size={18} /></button>
      </div>
    </div>
  );
 }
