import { useState, type ReactNode } from 'react';
import type { Adapter } from '../realtime/provider-options';
import { RequestAccess } from './RequestAccess';

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
  recovery,
  recoveryAvailable,
  onRecovery,
  requestAccess = false,
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
  recovery: boolean;
  recoveryAvailable: boolean;
  onRecovery: (enabled: boolean) => void;
  requestAccess?: boolean;
}) {
  const [showKeys, setShowKeys] = useState(false);
  const placeholders: Partial<Record<keyof PersonalKeys, string>> = {
    azure_endpoint: 'https://<resource>.openai.azure.com',
    azure_deployment: 'gpt-live-1',
    elevenlabs_agent_id: 'agent_…',
  };
  const field = (name: keyof PersonalKeys, label: string, secret = true) => (
    <label key={name}>
      {label}
      <input
        type={secret && !showKeys ? 'password' : 'text'}
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholders[name]}
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
      {adapter === 'openai' && recoveryAvailable && (
        <label className="recovery-choice">
          <input
            type="checkbox"
            checked={recovery}
            disabled={disabled}
            onChange={(event) => onRecovery(event.target.checked)}
          />{' '}
          Allow one Azure recovery for this session. Both providers may incur charges.
        </label>
      )}
      {source === 'platform' ? (
        <>
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
          {requestAccess && !disabled && <RequestAccess />}
        </>
      ) : (
        <>
          <p className="muted">
            No invitation required. Your providers bill your accounts. Keys are held in memory for
            this session only and clear after you start.
          </p>
          <details className="key-details">
            <summary>How your keys are handled</summary>
            <p className="muted">
              Keys are sent once to this backend and its configured worker, and held in memory for
              this session only. They are not saved in your browser or a database. Fields clear
              after submission; re-enter keys for another session.
            </p>
          </details>
          <label className="show-keys">
            <input
              type="checkbox"
              checked={showKeys}
              disabled={disabled}
              onChange={(event) => setShowKeys(event.target.checked)}
            />{' '}
            Show keys while typing
          </label>
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
          {(adapter === 'azure' || recovery) && (
            <>
              {field('azure_key', 'Azure API key')}
              {field('azure_endpoint', 'Azure resource HTTPS origin', false)}
              {field('azure_deployment', 'Azure deployment (default gpt-live-1)', false)}
            </>
          )}
          {field('tavily_key', 'Tavily API key (optional web search)')}
          <p className="muted">No automatic use of platform keys or platform-funded recovery.</p>
        </>
      )}
    </fieldset>
  );
}
