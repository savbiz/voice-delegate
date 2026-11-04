import { useRef, useState } from 'react';
import { Button } from './Button';

type Status = 'idle' | 'sending' | 'sent' | 'error';

/**
 * Asks the owner for an invitation; the backend forwards it as a notification. With `email`,
 * the owner can approve remotely and the code is emailed to the visitor.
 */
export function RequestAccess({ email = false }: { email?: boolean }) {
  const [contact, setContact] = useState('');
  const [note, setNote] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState('');
  // Blocks a second click that lands before React re-renders the disabled button.
  const inFlight = useRef(false);
  async function send() {
    if (inFlight.current) return;
    inFlight.current = true;
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
        setMessage(
          email
            ? 'Request sent. If it is approved, the owner will email you an invitation code.'
            : 'Request sent. The owner will reply with an invitation code.',
        );
        return;
      }
      const detail =
        response.status === 429
          ? 'Too many requests; try again later.'
          : response.status === 422 && email
            ? 'Enter a valid email address.'
            : undefined;
      setStatus('error');
      setMessage(detail ?? 'Could not send the request. Try again later.');
    } catch {
      setStatus('error');
      setMessage('Could not send the request. Try again later.');
    } finally {
      inFlight.current = false;
    }
  }
  if (status === 'sent') {
    // The form is gone once sent, so a request cannot be submitted twice from this page.
    return (
      <details className="key-details request-access" open>
        <summary>No invitation code? Request access</summary>
        <p role="status" aria-live="polite" className="request-access-sent">
          {message}
        </p>
      </details>
    );
  }
  return (
    <details className="key-details request-access">
      <summary>No invitation code? Request access</summary>
      <p className="muted">
        {email
          ? 'Leave your email. The owner is notified through ntfy.sh and, if approved, emails you an invitation code. This server keeps your address only until the owner decides (at most 7 days); afterwards only a hash remains, to prevent repeated requests.'
          : 'Leave an email or other way to reach you. It is sent to the owner through ntfy.sh as a notification, and the owner may reply with a code. This server stores nothing.'}
      </p>
      <label>
        {email ? 'Your email' : 'How to reach you'}
        <input
          type={email ? 'email' : 'text'}
          autoComplete="email"
          maxLength={120}
          value={contact}
          disabled={status === 'sending'}
          onChange={(event) => setContact(event.target.value)}
        />
      </label>
      <label>
        Note (optional)
        <input
          type="text"
          maxLength={300}
          value={note}
          disabled={status === 'sending'}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <Button
        disabled={contact.trim().length < 3 || status === 'sending'}
        onClick={() => void send()}
      >
        {status === 'sending' ? 'Sending…' : 'Request access'}
      </Button>
      <p role="status" aria-live="polite">
        {message}
      </p>
    </details>
  );
}
