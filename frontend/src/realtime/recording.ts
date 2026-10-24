/** Explicit browser-only audio capture; no upload or automatic recording. */
export type AudioRecording = {
  microphone(stream: MediaStream): void;
  assistant(stream: MediaStream): void;
  stop(): void;
};
export function recordAudio(
  stream: MediaStream,
  completed: (blob: Blob) => void,
  status: (message: string) => void,
): AudioRecording {
  const context = new AudioContext();
  let recorder: MediaRecorder | undefined;
  let mixer: GainNode | undefined;
  let microphone: MediaStreamAudioSourceNode | undefined;
  let assistant: MediaStreamAudioSourceNode | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    clearTimeout(timer);
    microphone?.disconnect();
    assistant?.disconnect();
    mixer?.disconnect();
    void context.close().catch(() => undefined);
  };
  try {
    const destination = context.createMediaStreamDestination();
    mixer = context.createGain();
    mixer.gain.value = 0.5;
    mixer.connect(destination);
    const connect = (input: MediaStream) => {
      const node = context.createMediaStreamSource(input);
      node.connect(mixer!);
      return node;
    };
    microphone = connect(stream);
    const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find((type) =>
      MediaRecorder.isTypeSupported(type),
    );
    recorder = new MediaRecorder(destination.stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    let bytes = 0;
    const stop = () => {
      if (recorder?.state !== 'inactive') recorder?.stop();
    };
    recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size) {
        chunks.push(event.data);
        bytes += event.data.size;
        if (bytes >= 20 * 1024 * 1024) {
          status('Audio recording reached its size limit; the conversation can continue.');
          stop();
        }
      }
    });
    recorder.addEventListener('stop', () => {
      const blob = new Blob(chunks, { type: recorder?.mimeType || mimeType || 'audio/webm' });
      chunks.length = 0;
      cleanup();
      if (blob.size) {
        completed(blob);
        status('Audio ready to download. Save it before reloading or leaving Live voice.');
      } else status('No audio was recorded.');
    });
    recorder.addEventListener('error', () => {
      status('Audio recording failed; any captured audio will be offered for download.');
      stop();
      cleanup();
    });
    recorder.start(1000);
    void context.resume().catch(() => {
      status('Audio capture could not start; check browser permissions.');
      stop();
    });
    timer = setTimeout(() => {
      status('Audio recording reached five minutes; the conversation can continue.');
      stop();
    }, 300000);
    status('Recording microphone and assistant locally. The recording is not uploaded.');
    return {
      microphone: (next) => {
        if (!cleaned) {
          microphone?.disconnect();
          microphone = connect(next);
        }
      },
      assistant: (next) => {
        if (!cleaned) {
          assistant?.disconnect();
          assistant = connect(next);
        }
      },
      stop,
    };
  } catch (error) {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    cleanup();
    throw error;
  }
}
