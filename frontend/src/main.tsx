import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './style.css';
import { isNativeClient } from './native';
import { inject } from '@vercel/analytics';
import { shouldCountVisitors, stripLocation } from './analytics';

document.documentElement.classList.toggle('native-app', isNativeClient());

if (
  shouldCountVisitors({
    production: import.meta.env.PROD,
    native: isNativeClient(),
    hostname: window.location.hostname,
    doNotTrack: navigator.doNotTrack,
  })
) {
  inject({ mode: 'production', beforeSend: stripLocation });
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
