# Capacitor mobile preview

Capacitor packages the existing React frontend into an iOS/iPadOS or Android app.
It does not change the browser version into a native app automatically. App Store
and Google Play publication require separate builds, signing, accounts and review.
The backend and the single `delegate_task` voice-tool contract stay the same.

This is an experimental, opt-in scaffold. Native web assets and deterministic
browser/API tests can be verified without a provider key. An unsigned iOS Simulator
build was verified on 2026-11-01 with Xcode 27.1 and the iOS Simulator 27.1 SDK.
The maintainer also reported a successful Android `:app:assembleDebug` build on
2026-11-01 (16 seconds, 71 executed tasks). A subsequent local build also compiled
`:app:assembleDebugAndroidTest`; instrumented tests were not executed. These are compilation checks; simulator
launch, physical-device audio, Bluetooth, recording export and store acceptance are pending.
The generated launcher icons and splash screens are placeholders, not store assets.

## Build the packaged frontend

Use Node.js 24 and the declared pnpm version. Run commands from `frontend/` only:

```sh
cd frontend
pnpm install --frozen-lockfile
export VOICE_NATIVE_BUILD=true
export VITE_API_BASE_URL=https://voice-delegate-api-production.up.railway.app
pnpm native:build
pnpm native:sync
```

`VOICE_NATIVE_BUILD` is a local tooling opt-in, not a backend variable. `native:build`
creates `dist-native/`; the normal Vercel build still creates `dist/`.
`native:sync` rebuilds and copies the local assets into the checked-in iOS and Android
projects. Rebuild and sync after changing frontend code or public build variables.
Neither command calls a voice provider. The default offline example needs no microphone,
invitation or provider key and uses the existing scripted scenario.

The API URL must be an explicit canonical HTTPS origin without a trailing slash,
path, username or password. Local HTTP Vite proxies do not exist inside a packaged
app. Use a configured HTTPS backend when testing network features.
Provider keys and invitation mappings belong on the backend, never in the bundle.

The packaged app loads local assets rather than Vercel through `server.url`.
The native build embeds a Content Security Policy restricted to the configured API
origin. Native HTTP/cookie overrides and native console logging are disabled;
requests retain the existing Origin, invitation and ownership-key checks.

## Open the projects

For iOS and iPadOS, install Xcode 26 or newer on macOS and its required SDKs:

```sh
pnpm exec cap open ios
```

Select an appropriate simulator or your own device. Choose your development team
in Xcode for physical-device signing; no team, certificate or provisioning profile
is committed here. The project uses Swift Package Manager. The microphone usage
description is included; camera permission and background-audio capability are not.

An unsigned simulator build can be reproduced without starting a provider session:

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -project ios/App/App.xcodeproj -scheme App -configuration Debug \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath ../.local/ios-build CODE_SIGNING_ALLOWED=NO build
```

The explicit `DEVELOPER_DIR` is useful when `xcode-select -p` still points at
Command Line Tools. It does not change the machine's global developer selection.


For Android, install Android Studio, Android SDK 36 and JDK 21:

```sh
pnpm exec cap open android
```

The project permits network access and microphone capture, disables cleartext traffic
and app backup, and does not require a microphone for installing the offline demo.
Do not commit local SDK paths, signing material, store service-account files or keys.

The app identifier is `io.github.savbiz.voicedelegate`. Review identifiers, branding,
version/build numbers and signing before creating any store submission.
`package.json` supplies the Android version name; the native build synchronizes the
iOS marketing version. Store upload build numbers are managed separately.

## Explicit live testing

Native voice is **disabled by default** even when the backend has a real key.
To opt into a device test, rebuild and sync with:

```sh
export VITE_NATIVE_LIVE=true
pnpm native:sync
```

Configure these backend values through its environment, preserving the existing
web origin and all invitations/quotas:

```sh
VOICE_NATIVE_CLIENTS=true
VOICE_ALLOWED_ORIGINS='["https://voice-delegate.vercel.app","capacitor://localhost","https://localhost"]'
```

The exact `capacitor://localhost` iOS origin is accepted only when
`VOICE_NATIVE_CLIENTS=true`; the flag does not add any origins automatically.
Android uses `https://localhost`. Origins identify the app's local web content,
not the backend's address. Keep `VOICE_ALLOWED_HOSTS` set to the backend's own host.
No deployed environment is changed by this PR or by building the mobile preview.

Enter an invitation in the app. A real backend provider key and starting a live
conversation incur the provider's usage charges. A permission prompt appears only
when starting; a denied permission must leave the app usable and allow retry.
Native backgrounding closes the owned session and releases local media; there is
no background-call support or automatic call resumption. Closing is best effort
and backend session expiry remains the final cleanup boundary.

## Acceptance checklist

- Build and sync with native voice disabled; start and stop the offline example without API calls.
- Launch the compiled project on a simulator, then a physical iPhone/iPad and Android device.
- Test documentation search with an invitation and the explicit native Origin allowlist.
- Opt into voice only when ready for provider charges; test microphone permission denied,
  then granted, a short conversation, delegation and explicit cancellation.
- Test speaker/headphones/Bluetooth, mute, interruption and network loss.
- Switch apps and lock the screen: local media must stop and the server must receive close,
  or eventually expire the session. Returning must require a new explicit start.
- Verify debug consent, recording consent, native recording export and notice links.
  Browser download behaviour is not proof that native export works.
- Verify safe areas, landscape, large text and touch controls on real devices.
- Before distribution, review privacy disclosures, retention, store assets and the complete
  resolved Maven/SPM licence inventory. No store build or submission is claimed here.

See [frontend setup](../frontend/README.md), [configuration](configuration.md),
[API](api.md) and [live verification](milestones/live-verification.md).

Official references: [installation](https://capacitorjs.com/docs/getting-started),
[environment setup](https://capacitorjs.com/docs/getting-started/environment-setup),
[configuration](https://capacitorjs.com/docs/config),
[App Store](https://capacitorjs.com/docs/ios/deploying-to-app-store) and
[Google Play](https://capacitorjs.com/docs/android/deploying-to-google-play).
