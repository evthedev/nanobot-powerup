import React, { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatWindow from './components/ChatWindow';
import WelcomeScreen from './components/WelcomeScreen';
import Settings from './components/Settings';
import LogsPanel from './components/LogsPanel';
import './App.css';

const API = 'http://localhost:3001'; // Direct to Express — bypasses CRA proxy buffering

export default function App() {
  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [stats, setStats] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [serverOk, setServerOk] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [mainModel, setMainModel] = useState(null);

  // ── Boot ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    checkHealth();
    fetchConversations();
    fetchStats();
    fetchMainModel();
  }, []);

  async function checkHealth() {
    try {
      const r = await fetch(`${API}/api/health`);
      const data = await r.json();
      setServerOk(data.status === 'ok');
    } catch {
      setServerOk(false);
    }
  }

  async function fetchConversations() {
    try {
      const r = await fetch(`${API}/api/conversations`);
      const data = await r.json();
      setConversations(data);
    } catch (e) {
      console.error('Failed to fetch conversations', e);
    }
  }

  async function fetchMainModel() {
    try {
      const r = await fetch(`${API}/api/config`);
      const cfg = await r.json();
      const model = cfg?.agents?.model || cfg?.model || null;
      if (model) setMainModel(model);
    } catch {}
  }

  async function fetchStats() {
    try {
      const r = await fetch(`${API}/api/stats`);
      const data = await r.json();
      setStats(data);
    } catch {}
  }

  // ── Conversation actions ──────────────────────────────────────────────────
  const createConversation = useCallback(async (initialMessage) => {
    const r = await fetch(`${API}/api/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New Conversation' })
    });
    const conv = await r.json();
    setConversations(prev => [conv, ...prev]);
    setActiveConvId(conv.id);
    setMessages([]);
    if (initialMessage) {
      await sendMessage(conv.id, initialMessage);
    }
    return conv;
  }, []);

  const selectConversation = useCallback(async (id) => {
    setShowLogs(false);
    setActiveConvId(id);
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/conversations/${id}/messages`);
      const msgs = await r.json();
      setMessages(msgs);
    } catch (e) {
      console.error('Failed to load messages', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const deleteConversation = useCallback(async (id) => {
    await fetch(`${API}/api/conversations/${id}`, { method: 'DELETE' });
    setConversations(prev => prev.filter(c => c.id !== id));
    if (activeConvId === id) {
      setActiveConvId(null);
      setMessages([]);
    }
    fetchStats();
  }, [activeConvId]);

  const renameConversation = useCallback(async (id, title) => {
    await fetch(`${API}/api/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    setConversations(prev => prev.map(c => c.id === id ? { ...c, title } : c));
  }, []);

  // ── Message sending ───────────────────────────────────────────────────────
  const sendMessage = useCallback(async (convId, content) => {
    const targetId = convId || activeConvId;
    if (!targetId || !content.trim()) return;

    // Optimistic user message
    const tempId = `temp-${Date.now()}`;
    const userMsg = {
      id: tempId,
      conversation_id: targetId,
      role: 'user',
      content: content.trim(),
      created_at: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMsg]);
    setStreaming(true);

    // Streaming assistant placeholder (let so new_message can advance it)
    let assistantTempId = `assistant-temp-${Date.now()}`;
    let assistantMsg = {
      id: assistantTempId,
      conversation_id: targetId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      streaming: true
    };
    setMessages(prev => [...prev, assistantMsg]);

    try {
      const response = await fetch(`${API}/api/conversations/${targetId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content.trim(), tempId: assistantTempId })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalMsgId = assistantTempId;

      streamLoop: while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          try {
            const event = JSON.parse(raw);
            if (event.type === 'delta') {
              setMessages(prev => prev.map(m =>
                m.id === assistantTempId
                  ? { ...m, content: m.content + event.content }
                  : m
              ));
            } else if (event.type === 'new_message') {
              // Subagent (or second agent turn) is about to stream — freeze the
              // current bubble and add a fresh streaming placeholder.
              setMessages(prev => prev.map(m =>
                m.id === assistantTempId ? { ...m, streaming: false } : m
              ));
              assistantTempId = event.tempId;
              setMessages(prev => [...prev, {
                id: assistantTempId,
                conversation_id: targetId,
                role: 'assistant',
                content: '',
                created_at: new Date().toISOString(),
                streaming: true,
              }]);
              // Re-show spinner for the incoming subagent message
              setStreaming(true);
            } else if (event.type === 'done') {
              // Finalise the bubble identified by tempId (may be a later subagent bubble)
              const tid = event.tempId || assistantTempId;
              finalMsgId = event.messageId;
              setMessages(prev => prev.map(m =>
                m.id === tid
                  ? { ...m, id: finalMsgId, content: event.content, streaming: false }
                  : m
              ));
              // Clear spinner immediately when message appears — don't wait for WS session to close.
              // If a new_message event follows (subagent), setStreaming(true) will re-enable it.
              setStreaming(false);
            } else if (event.type === 'error') {
              setMessages(prev => prev.map(m =>
                m.id === assistantTempId
                  ? { ...m, content: `⚠️ ${event.error}`, streaming: false, error: true }
                  : m
              ));
            } else if (event.type === 'stream_end') {
              // Server signals stream is fully done — exit immediately rather than
              // waiting for TCP connection close (can lag several seconds).
              console.log('[stream] got stream_end → breaking streamLoop');
              break streamLoop;
            }
          } catch {}
        }
      }

      // Refresh conversation list to get updated title/timestamp
      fetchConversations();
      fetchStats();

    } catch (err) {
      setMessages(prev => prev.map(m =>
        m.id === assistantTempId
          ? { ...m, content: `⚠️ Connection error: ${err.message}`, streaming: false, error: true }
          : m
      ));
    } finally {
      setStreaming(false);
    }
  }, [activeConvId]);

  // ── Handle new chat from welcome screen ──────────────────────────────────
  const handleNewChat = useCallback(async (message) => {
    await createConversation(message);
  }, [createConversation]);

  // ── Handle send from chat window ─────────────────────────────────────────
  const handleSend = useCallback(async (content) => {
    if (!activeConvId) {
      await createConversation(content);
    } else {
      await sendMessage(activeConvId, content);
    }
  }, [activeConvId, createConversation, sendMessage]);

  const activeConv = conversations.find(c => c.id === activeConvId);

  return (
    <div className={`app-layout ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
      <Sidebar
        conversations={conversations}
        activeConvId={activeConvId}
        onSelect={selectConversation}
        onNew={() => { setShowLogs(false); setActiveConvId(null); setMessages([]); }}
        onDelete={deleteConversation}
        onRename={renameConversation}
        stats={stats}
        serverOk={serverOk}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(p => !p)}
        onSettings={() => setShowSettings(true)}
        showLogs={showLogs}
        onLogs={() => setShowLogs(p => !p)}
      />

      <main className="main-area">
        {showLogs ? (
          <LogsPanel mainModel={mainModel} />
        ) : activeConvId ? (
          <ChatWindow
            conversation={activeConv}
            messages={messages}
            onSend={handleSend}
            streaming={streaming}
            loading={loading}
            onToggleSidebar={() => setSidebarOpen(p => !p)}
            sidebarOpen={sidebarOpen}
          />
        ) : (
          <WelcomeScreen
            onNewChat={handleNewChat}
            stats={stats}
            onToggleSidebar={() => setSidebarOpen(p => !p)}
            sidebarOpen={sidebarOpen}
          />
        )}
      </main>
    </div>
  );
}
