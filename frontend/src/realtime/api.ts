/** Backend requests for a live session, with user-facing error messages. */

/** A created session as the browser owns it. */
export type OwnedSession = {
  id: string;
  key: string;
  accessCode: string;
  debugRecording?: boolean;
  azureRecovery?: boolean;
};

const STATUS_MESSAGES: Record<number, string> = {
  401: 'Your invitation is missing, invalid or revoked.',
  429: 'Demo allowance reached or another conversation is active. Try again later.',
  503: 'New conversations are temporarily unavailable.',
};

function failure(path: string, status: number): string {
  if (status === 502)
    return path.endsWith('/config')
      ? 'The backend is unavailable. For local development, start the backend with make be and retry.'
      : 'Voice connection failed. Check backend logs and the selected provider configuration.';
  return (
    STATUS_MESSAGES[status] ?? `Request failed (${status}). Check server configuration and access.`
  );
}

const timedOut = (error: unknown) => error instanceof Error && error.name === 'TimeoutError';

export function createApi(getAccessCode: () => string) {
  function requestOptions(
    owner?: OwnedSession,
    body?: unknown,
    timeout = 35000,
    accessCode = owner?.accessCode ?? getAccessCode(),
  ): RequestInit {
    return {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(accessCode ? { Authorization: `Bearer ${accessCode}` } : {}),
        ...(owner ? { 'X-Session-Key': owner.key } : {}),
      },
      body: JSON.stringify(body ?? {}),
      signal: AbortSignal.timeout(timeout),
    };
  }

  async function request<T>(
    path: string,
    owner?: OwnedSession,
    body?: unknown,
    timeout = 35000,
    accessCode?: string,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL ?? ''}/api${path}`,
        requestOptions(owner, body, timeout, accessCode),
      );
    } catch (error) {
      throw new Error(
        timedOut(error)
          ? 'The server took too long to respond. Please try again.'
          : 'Could not reach the server. Check your connection and try again.',
        { cause: error },
      );
    }
    if (!response.ok) throw new Error(failure(path, response.status));
    try {
      return await response.json();
    } catch (error) {
      throw new Error(
        timedOut(error)
          ? 'The server took too long to respond. Please try again.'
          : 'The server returned an unreadable response. Please try again.',
        { cause: error },
      );
    }
  }

  return { request, requestOptions };
}
