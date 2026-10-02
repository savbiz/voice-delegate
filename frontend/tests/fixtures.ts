export function installFakePeers() {
  const peers: FakePeer[] = [];
  class FakeChannel extends EventTarget {
    close() {
      this.dispatchEvent(new Event('close'));
    }
  }
  class FakePeer extends EventTarget {
    iceGatheringState = 'complete';
    connectionState = 'new';
    localDescription = { type: 'offer', sdp: 'v=0\r\n' };
    channel = new FakeChannel();
    constructor() {
      super();
      peers.push(this);
    }
    addTrack() {}
    createDataChannel() {
      return this.channel;
    }
    async createOffer() {
      return this.localDescription;
    }
    async setLocalDescription() {}
    async setRemoteDescription() {
      this.connectionState = 'connected';
      this.channel.dispatchEvent(
        new MessageEvent('message', { data: JSON.stringify({ type: 'session.started' }) }),
      );
    }
    close() {
      this.connectionState = 'closed';
    }
  }
  Object.defineProperty(window, 'RTCPeerConnection', { value: FakePeer });
  Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
    value: async () => new MediaStream(),
  });
  Object.defineProperty(window, '__peers', { value: peers });
}

export function failLatestPeer() {
  const peer = (
    window as unknown as { __peers: (EventTarget & { connectionState: string })[] }
  ).__peers.at(-1);
  if (!peer) throw new Error('No peer was created');
  peer.connectionState = 'failed';
  peer.dispatchEvent(new Event('connectionstatechange'));
}
