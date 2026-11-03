import type { CostSummary } from '../realtime/costs';
import { costText } from '../realtime/costs';
import { adapterNames, type Adapter, type VoiceOptions } from '../realtime/provider-options';

export function ProviderChoice({
  options,
  value,
  disabled,
  onChange,
}: {
  options: VoiceOptions;
  value: Adapter;
  disabled: boolean;
  onChange: (adapter: Adapter) => void;
}) {
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
        {options.available_adapters.map((adapter) => (
          <option key={adapter} value={adapter}>
            {adapterNames[adapter]}
          </option>
        ))}
      </select>
      <small>
        Chosen for the next session. Provider availability and model choices are controlled by this
        service.
      </small>
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
