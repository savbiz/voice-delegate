import type { ReactNode } from 'react';
import type { Adapter } from '../realtime/provider-options';

export type ApiSource = 'platform' | 'personal';
export type PersonalKeys = Partial<
  Record<
    | 'openai_key'
    | 'tavily_key'
    | 'elevenlabs_key'
    | 'elevenlabs_agent_id'
    | 'elevenlabs_webhook_token'
    | 'azure_key'
    | 'azure_endpoint'
    | 'azure_deployment',
    string
  >
>;

export function ApiAccess({
  source,
  onSource,
  keys,
  onKeys,
  adapter,
  disabled,
  code,
  onCode,
  webhookUrl,
  children,
}: {
  source: ApiSource;
  onSource: (source: ApiSource) => void;
  keys: PersonalKeys;
  onKeys: (keys: PersonalKeys) => void;
  adapter: Adapter | undefined;
  disabled: boolean;
  code: string;
  onCode: (code: string) => void;
  webhookUrl?: string;
  children?: ReactNode;
}) {
  const field = (name: keyof PersonalKeys, label: string, secret = true) => (
    <label key={name}>
      {label}
      <input
        type={secret ? 'password' : 'text'}
        autoComplete="off"
        spellCheck={false}
        maxLength={name === 'elevenlabs_agent_id' ? 200 : name === 'azure_endpoint' ? 512 : 4096}
        value={keys[name] ?? ''}
        disabled={disabled}
        onChange={(event) => onKeys({ ...keys, [name]: event.target.value || undefined })}
      />
    </label>
  );
  return (
    <fieldset className="api-access">
      <legend>API access</legend>
      <div className="api-source">
        <label>
          <input
            type="radio"
            disabled={disabled}
            name="api-source"
            checked={source === 'personal'}
            onChange={() => onSource('personal')}
          />{' '}
          Your API keys
        </label>
        <label>
          <input
            type="radio"
            disabled={disabled}
            name="api-source"
            checked={source === 'platform'}
            onChange={() => onSource('platform')}
          />{' '}
          Platform API
        </label>
      </div>
      {children}
      {source === 'platform' ? (
        <label>
          Personal invitation code
          <input
            type="password"
            autoComplete="off"
            value={code}
            placeholder="Required on the hosted platform"
            onChange={(event) => onCode(event.target.value)}
          />
        </label>
      ) : (
        <>
          <p className="muted">
            No invitation required. Your providers bill your accounts. Keys are sent to this backend
            and its configured worker and held in memory for this session only. They are not saved
            in your browser or a database. Fields clear after submission; re-enter keys for another
            session.
          </p>
          {field(
            'openai_key',
            adapter === 'elevenlabs' || adapter === 'azure'
              ? 'OpenAI API key (optional worker)'
              : 'OpenAI API key (voice and worker)',
          )}
          {adapter === 'elevenlabs' && (
            <>
              {field('elevenlabs_key', 'ElevenLabs API key')}
              {field('elevenlabs_agent_id', 'ElevenLabs Agent ID', false)}
              {field('elevenlabs_webhook_token', 'ElevenLabs webhook token')}
              <p className="muted">
                Your private agent must use this backend’s delegate_task webhook. The API key alone
                does not configure the agent. An optional OpenAI key enables the language-model
                worker; otherwise it uses the offline planner.
              </p>
              {webhookUrl && (
                <p className="muted">
                  Webhook URL: <code>{webhookUrl}</code>. Configure an async POST tool named
                  delegate_task with a 120-second timeout, a required goal string,
                  X-Voice-Webhook-Token from your ElevenLabs secret, and X-Voice-Conversation-Id
                  from system__conversation_id.
                </p>
              )}
            </>
          )}
          {adapter === 'azure' && (
            <>
              {field('azure_key', 'Azure API key')}
              {field('azure_endpoint', 'Azure resource HTTPS origin', false)}
              {field('azure_deployment', 'Azure deployment (default gpt-realtime)', false)}
            </>
          )}
          {field('tavily_key', 'Tavily API key (optional web search)')}
          <p className="muted">No automatic use of platform keys or platform-funded recovery.</p>
        </>
      )}
    </fieldset>
  );
}
