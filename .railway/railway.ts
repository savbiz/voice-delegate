import { defineRailway, github, project, service, volume } from "railway/iac";

// Railway Infrastructure as Code for the hosted API. Replaces the deprecated railway.json.
// This repository manages only its own resources in the environment.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "voice-delegate-api";

export default defineRailway(() => {
  // Holds the quota, feedback and debug SQLite stores (VOICE_*_DATABASE, VOICE_DEBUG_DIRECTORY).
  const data = volume("voice-delegate-api-voice-delegate-data", {
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
    allowOnlineResize: true,
    region: "europe-west4-drams3a",
    sizeMB: 500,
  });

  const api = service("voice-delegate-api", {
    source: github("savbiz/voice-delegate", { branch: "main", checkSuites: false, rootDirectory: "/" }),
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "deployment/Dockerfile.backend" },
    healthcheck: "/healthz",
    healthcheckTimeout: 300,
    replicas: { "europe-west4-drams3a": 1 },
    deploy: { sleepApplication: true, restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 10 },
    volumeMounts: { "/app/.local": data },
  });

  // Secrets and settings stay in Railway; this file never reads or writes variables.
  return project("voice-delegate", {
    variables: { managed: false },
    resources: [api, data],
  });
});
