import { useState } from 'react';

type Status = 'idle' | 'sending' | 'sent' | 'error';

/** Asks the owner for an invitation; the backend forwards it as a notification. */
export function RequestAccess() {
  const [contact, setContact] = useState('');
  const [note, setNote] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState('');
  async function send() {
    setStatus('sending');
    try {
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL ?? ''}/api/access-request`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ contact: contact.trim(), note: note.trim() }),
          signal: AbortSignal.timeout(8000),
        },
      );
      if (response.ok) {
        setStatus('sent');
        setMessage('Request sent. The owner will reply with an invitation code.');
        return;
      }
      const detail = response.status === 429 ? 'Too many requests; try again later.' : undefined;
      setStatus('error');
      setMessage(detail ?? 'Could not send the request. Try again later.');
    } catch {
      setStatus('error');
      setMessage('Could not send the request. Try again later.');
    }
  }
  return (
    <details className="key-details request-access">
      <summary>No invitation code? Request access</summary>
      <p className="muted">
        Leave an email or other way to reach you. The owner is notified and may reply with a code.
        Nothing else is stored.
      </p>
      <label>
        How to reach you
        <input
          type="text"
          autoComplete="email"
          maxLength={120}
          value={contact}
          disabled={status === 'sending' || status === 'sent'}
          onChange={(event) => setContact(event.target.value)}
        />
      </label>
      <label>
        Note (optional)
        <input
          type="text"
          maxLength={300}
          value={note}
          disabled={status === 'sending' || status === 'sent'}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={contact.trim().length < 3 || status === 'sending' || status === 'sent'}
        onClick={() => void send()}
      >
        Request access
      </button>
      <p role="status" aria-live="polite">
        {message}
      </p>
    </details>
  );
}
