# ADR 004: Static React frontend and persistent Python backend

Status: accepted.

Context: the project needs a React browser UI and independent frontend/backend deployments without coupling voice transport to a UI framework.

Decision: use React 19, TypeScript, Vite 8 and Tailwind 4 in frontend/, and a uv Python workspace containing backend/. Keep the WebRTC controller outside React rendering and let an effect own its lifetime. Use Vitest for deterministic logic and Playwright for browser behavior. Keep LangGraph out until an actual delegated workflow is introduced.

Consequences: frontend and backend deploy independently; the backend allows one configured CORS origin and requires a shared access code in production. This is a controlled demo gate, not user identity. Vercel builds only frontend/. Railway or Render runs one long-lived Python process. A free scripted mode exercises UI without provider calls; it makes no claims about model behavior or real latency.

Sources: [Vite](https://vite.dev/guide/), [Tailwind Vite integration](https://tailwindcss.com/docs/installation/using-vite), [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/).
