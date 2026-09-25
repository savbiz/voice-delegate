# ADR 004: Static React frontend and persistent Python backend

Status: accepted.

Context: the project needs a React browser UI and independent frontend/backend deployments without coupling voice transport to a UI framework.

Decision: use React 19, TypeScript, Vite 8 and Tailwind 4 in frontend/, and a uv Python workspace containing backend/. Keep the WebRTC controller outside React rendering and let an effect own its lifetime. Use Vitest for deterministic logic and Playwright for browser behavior. LangGraph was added for the delegated worker workflow.

Consequences: frontend and backend deploy independently; the backend allows one configured CORS origin and supports a shared code or personal invitations. Personal invitations are required for the protected public demo; shared code mode is for private testing. Vercel builds only frontend/. Railway or Render runs one long-lived Python process. A free scripted mode exercises UI without provider calls; it makes no claims about model behavior or real latency.

Sources: [Vite](https://vite.dev/guide/), [Tailwind Vite integration](https://tailwindcss.com/docs/installation/using-vite), [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/).
