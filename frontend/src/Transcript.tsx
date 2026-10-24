import { useEffect, useRef, useState } from 'react';
import type { ChatMessage } from './realtime/store';

export function Transcript({ messages }: { messages: ChatMessage[] }) {
  const viewport = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  useEffect(() => {
    if (following.current && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [messages]);
  return (
    <section className="conversation" aria-label="Conversation transcript">
      <div className="conversation-heading">
        <h2>Conversation</h2>
        <span className="muted">Live transcript</span>
      </div>
      <div
        className="chat-scroll"
        ref={viewport}
        onScroll={() => {
          const element = viewport.current;
          if (!element) return;
          following.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
          setShowLatest(!following.current);
        }}
      >
        {messages.length === 0 ? (
          <div className="chat-empty">
            <p>Your conversation will appear here.</p>
            <small>Start a conversation and speak naturally.</small>
          </div>
        ) : (
          <ol className="chat-messages" aria-label="Transcript messages" aria-live="off">
            {messages.map((message) => (
              <li key={message.id} className={`chat-message ${message.speaker}`}>
                <span className="chat-speaker">
                  {message.speaker === 'user' ? 'You' : 'Assistant'}
                </span>
                <p>{message.text}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
      {showLatest && (
        <button
          onClick={() => {
            following.current = true;
            setShowLatest(false);
            if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
          }}
        >
          Latest messages ↓
        </button>
      )}
    </section>
  );
}
