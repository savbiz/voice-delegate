/** Only transport failures justify replacing a billable provider connection. */
export function shouldRecover(event: string, connectionState?: string): boolean {
  return (
    event === 'data-channel-close' ||
    (event === 'connectionstatechange' && connectionState === 'failed')
  );
}
