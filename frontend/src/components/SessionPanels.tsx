import { isNativeClient } from '../native';
import type { ApiSource } from './ApiAccess';
import type { CostSummary } from '../realtime/costs';
import { costText } from '../realtime/costs';
import { adapterNames, type Adapter, type VoiceOptions } from '../realtime/provider-options';

export function ProviderChoice({
  options,
  value,
  disabled,
  onChange,
  source,
}: {
  options: VoiceOptions;
  source: ApiSource;
  value: Adapter;
  disabled: boolean;
  onChange: (adapter: Adapter) => void;
}) {
  const providers = (Object.keys(adapterNames) as Adapter[]).filter(
    (adapter) => !isNativeClient() || adapter !== 'elevenlabs',
  );
  const unavailable = providers.filter((adapter) => !options.available_adapters.includes(adapter));
  return (
    <label className="provider-choice">
      Voice provider
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => {
          const adapter = event.target.value as Adapter;
          if (options.available_adapters.includes(adapter)) onChange(adapter);
        }}
      >
        {providers.map((adapter) => (
          <option
            key={adapter}
            value={adapter}
            disabled={!options.available_adapters.includes(adapter)}
          >
            {adapterNames[adapter]}
            {!options.available_adapters.includes(adapter)
              ? source === 'personal'
                ? ' — unavailable on this server'
                : ' — not configured'
              : ''}
          </option>
        ))}
      </select>
      <small>
        {source === 'platform'
          ? 'Uses the selected provider’s credentials configured on this backend.'
          : 'Uses your credentials for the selected provider, for this session only.'}
        {options.available_adapters.length > 0 &&
          unavailable.length > 0 &&
          (source === 'personal'
            ? ' ElevenLabs is unavailable until the server operator sets its public webhook URL; it works on a deployed backend.'
            : ` Not configured: ${unavailable.map((adapter) => adapterNames[adapter]).join(', ')}.`)}
      </small>
      {options.available_adapters.length === 0 && (
        <small className="notice" role="alert">
          No voice provider is configured on this server. Ask the operator to add a provider key, or
          switch to Your API keys.
        </small>
      )}
    </label>
  );
}

export function SpeakingStatus({
  activity,
}: {
  activity: { user: boolean; assistant: boolean } | undefined;
}) {
  return (
    <p className="speaking-status" aria-label="Observed audio activity">
      {activity
        ? activity.user && activity.assistant
          ? 'Both audio streams active'
          : activity.user
            ? 'Your microphone is active'
            : activity.assistant
              ? 'Assistant audio is active'
              : 'Listening · no speech energy detected'
        : 'Audio activity unavailable'}
      <small>
        Local audio-energy observation; provider speech detection controls interruption.
      </small>
    </p>
  );
}

export function CostPanel({ cost }: { cost: CostSummary | undefined }) {
  if (!cost) return null;
  return (
    <section className="cost-panel" aria-label="Session cost estimate">
      <h2>
        Session estimate <span className="muted">{cost.final ? 'Finished' : 'In progress'}</span>
      </h2>
      <p>{costText(cost)}</p>
      <dl className="cost-breakdown">
        {Object.entries(cost.components).map(([component, amount]) => (
          <div key={component}>
            <dt>{component.replace('_', ' ')}</dt>
            <dd>${amount.toFixed(6)}</dd>
          </div>
        ))}
      </dl>
      {cost.partial && (
        <p className="notice">
          Partial estimate: some usage or tariffs are unavailable.
          {cost.unpriced.length > 0 && <> Unpriced: {cost.unpriced.join(', ')}.</>}
        </p>
      )}
      <small>Price version: {cost.version}. Not a spending cap or provider invoice.</small>
    </section>
  );
}
