import React, { useState, useEffect, useCallback } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useParams } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ChatWindow from './components/ChatWindow';
import WelcomeScreen from './components/WelcomeScreen';
import Settings from './components/Settings';
import LogsPanel from './components/LogsPanel';
import TelegramView from './components/TelegramView';
import './App.css';

const API = process.env.REACT_APP_API_URL || '';

// ── Inner app — has access to router hooks ────────────────────────────────────
function AppInner() {
  const navigate = useNavigate();

  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [stats, setStats] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 768);
  const [serverOk, setServerOk] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [mainModel, setMainModel] = useState(null);

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

  const loadConversation = useCallback(async (id) => {
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

  const isMobile = () => window.innerWidth <= 768;

  const selectConversation = useCallback((id) => {
    navigate(`/chat/${id}`);
    if (isMobile()) setSidebarOpen(false);
  }, [navigate]);

  const deleteConversation = useCallback(async (id) => {
    await fetch(`${API}/api/conversations/${id}`, { method: 'DELETE' });
    setConversations(prev => prev.filter(c => c.id !== id));
    if (activeConvId === id) {
      setActiveConvId(null);
      setMessages([]);
      navigate('/');
    }
    fetchStats();
  }, [activeConvId, navigate]);

  const renameConversation = useCallback(async (id, title) => {
    await fetch(`${API}/api/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    setConversations(prev => prev.map(c => c.id === id ? { ...c, title } : c));
  }, []);

  // sendMessageToConv is defined first so createConversation can reference it in deps
  const sendMessageToConv = useCallback(async (convId, content) => {
    if (!convId || !content.trim()) return;

    const tempId = `temp-${Date.now()}`;
    const userMsg = {
      id: tempId,
      conversation_id: convId,
      role: 'user',
      content: content.trim(),
      created_at: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMsg]);
    setStreaming(true);

    let assistantTempId = `assistant-temp-${Date.now()}`;
    setMessages(prev => [...prev, {
      id: assistantTempId,
      conversation_id: convId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      streaming: true
    }]);

    let gotDone = false;

    try {
      const response = await fetch(`${API}/api/conversations/${convId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content.trim(), tempId: assistantTempId })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      streamLoop: while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        /* eslint-disable no-loop-func */
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          try {
            const event = JSON.parse(raw);
            if (event.type === 'delta') {
              const tid = assistantTempId;
              setMessages(prev => prev.map(m =>
                m.id === tid ? { ...m, content: m.content + event.content } : m
              ));
            } else if (event.type === 'new_message') {
              const prevTid = assistantTempId;
              setMessages(prev => prev.map(m =>
                m.id === prevTid ? { ...m, streaming: false } : m
              ));
              assistantTempId = event.tempId;
              const nextTid = assistantTempId;
              setMessages(prev => [...prev, {
                id: nextTid,
                conversation_id: convId,
                role: 'assistant',
                content: '',
                created_at: new Date().toISOString(),
                streaming: true,
              }]);
              setStreaming(true);
            } else if (event.type === 'done') {
              gotDone = true;
              const tid = event.tempId || assistantTempId;
              setMessages(prev => prev.map(m =>
                m.id === tid
                  ? { ...m, id: event.messageId, content: event.content, streaming: false }
                  : m
              ));
              setStreaming(false);
            } else if (event.type === 'error') {
              const tid = assistantTempId;
              setMessages(prev => prev.map(m =>
                m.id === tid
                  ? { ...m, content: `⚠️ ${event.error}`, streaming: false, error: true }
                  : m
              ));
            } else if (event.type === 'stream_end') {
              break streamLoop;
            }
          } catch {}
        }
        /* eslint-enable no-loop-func */
      }

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

      // Recovery: if the SSE stream closed without a confirmed `done` event the
      // connection dropped mid-response. The agent may still be running and will
      // save its reply to DB when it finishes. Poll the DB every few seconds
      // (with exponential back-off) until a new assistant message appears or we
      // reach the 10-minute ceiling.
      if (!gotDone) {
        const INTERVALS = [2, 3, 5, 8, 13, 21, 30, 30, 30, 30]; // seconds
        const DEADLINE = Date.now() + 10 * 60 * 1000;
        let lastAssistantId = null;

        // Capture the last known assistant message id so we can detect new ones
        try {
          const seed = await fetch(`${API}/api/conversations/${convId}/messages`);
          const seedMsgs = await seed.json();
          setMessages(seedMsgs); // replace streaming temp bubbles with DB state
          const last = [...seedMsgs].reverse().find(m => m.role === 'assistant');
          lastAssistantId = last?.id ?? null;
        } catch {}

        for (const delay of INTERVALS) {
          if (Date.now() >= DEADLINE) break;
          await new Promise(r => setTimeout(r, delay * 1000));
          try {
            const r = await fetch(`${API}/api/conversations/${convId}/messages`);
            const freshMsgs = await r.json();
            const newLast = [...freshMsgs].reverse().find(m => m.role === 'assistant');
            if (newLast && newLast.id !== lastAssistantId) {
              // A new assistant message arrived — surface it
              setMessages(freshMsgs);
              fetchConversations();
              fetchStats();
              break;
            }
          } catch { break; }
        }
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createConversation = useCallback(async (initialMessage) => {
    const r = await fetch(`${API}/api/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New Conversation' })
    });
    const conv = await r.json();
    setConversations(prev => [conv, ...prev]);
    navigate(`/chat/${conv.id}`);
    setMessages([]);
    if (initialMessage) {
      await sendMessageToConv(conv.id, initialMessage);
    }
    return conv;
  }, [navigate, sendMessageToConv]);

  const handleSend = useCallback(async (content) => {
    if (!activeConvId) {
      await createConversation(content);
    } else {
      await sendMessageToConv(activeConvId, content);
    }
  }, [activeConvId, createConversation, sendMessageToConv]);

  const handleNewChat = useCallback(async (message) => {
    if (isMobile()) setSidebarOpen(false);
    await createConversation(message);
  }, [createConversation]);

  const sidebarProps = {
    conversations,
    activeConvId,
    onSelect: selectConversation,
    onNew: () => navigate('/'),
    onDelete: deleteConversation,
    onRename: renameConversation,
    stats,
    serverOk,
    isOpen: sidebarOpen,
    onToggle: () => setSidebarOpen(p => !p),
    onSettings: () => setShowSettings(true),
    onLogs: () => navigate('/logs'),
  };

  return (
    <div className={`app-layout ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}

      {/* Mobile backdrop — tap to close sidebar */}
      {sidebarOpen && (
        <div className="mobile-backdrop" onClick={() => setSidebarOpen(false)} />
      )}

      <Sidebar {...sidebarProps} />

      <main className="main-area">
        <Routes>
          <Route path="/logs" element={
            <LogsPanel
              mainModel={mainModel}
              onToggleSidebar={() => setSidebarOpen(p => !p)}
              sidebarOpen={sidebarOpen}
            />
          } />
          <Route
            path="/telegram"
            element={
              <TelegramView
                onToggleSidebar={() => setSidebarOpen(p => !p)}
                sidebarOpen={sidebarOpen}
              />
            }
          />
          <Route
            path="/chat/:chatId"
            element={
              <ChatRoute
                conversations={conversations}
                activeConvId={activeConvId}
                messages={messages}
                loading={loading}
                streaming={streaming}
                onLoad={loadConversation}
                onSend={handleSend}
                onToggleSidebar={() => setSidebarOpen(p => !p)}
                sidebarOpen={sidebarOpen}
              />
            }
          />
          <Route
            path="/"
            element={
              <WelcomeScreen
                onNewChat={handleNewChat}
                stats={stats}
                onToggleSidebar={() => setSidebarOpen(p => !p)}
                sidebarOpen={sidebarOpen}
              />
            }
          />
        </Routes>
      </main>
    </div>
  );
}

// ── ChatRoute — loads messages when chatId changes ───────────────────────────
function ChatRoute({ conversations, activeConvId, messages, loading, streaming, onLoad, onSend, onToggleSidebar, sidebarOpen }) {
  const { chatId } = useParams();

  useEffect(() => {
    if (chatId && chatId !== activeConvId) {
      onLoad(chatId);
    }
  }, [chatId, activeConvId, onLoad]);

  const conv = conversations.find(c => c.id === chatId);

  return (
    <ChatWindow
      conversation={conv}
      messages={messages}
      onSend={onSend}
      streaming={streaming}
      loading={loading}
      onToggleSidebar={onToggleSidebar}
      sidebarOpen={sidebarOpen}
    />
  );
}

// ── Root with BrowserRouter ───────────────────────────────────────────────────
export default function App() {
  return (
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  );
}
