# Two-Node Split — Resolver / Streamer Design

Status: **design proposal**, 2026-11-03. Implementation in progress:
Phase 0 merged (PR #14), Phase 1 in PR (streamer config + compose +
contract tests); Phases 2–3 not started.
Basis: a full source trace of youtube-source **1.18.2** (the version pinned
in `config/application.yml`), summarised in §2. Companion to
`docs/AUDIT-2026-11.md` §"State of the art".

---

## 1. Problem and principle

YouTube's bot protection is not uniform across the operations this stack
performs. **Search and track resolution** (browse-shaped traffic: search
pages, Innertube metadata calls, high request diversity from one IP) is
what draws "sign in to confirm you're not a bot" challenges. **Streaming**,
by contrast, works reliably from a datacenter IP as long as the request is
properly authenticated.

Today a single Lavalink node does both jobs from one IP with one identity,
so the dirty traffic pattern and the valuable identity (the OAuth account)
share an egress address and a fate.

**Principle: separate the two ends.**

- The **resolver** does the bot-protected work — search and metadata
  resolution — and egresses through a rotating pool of mobile/residential
  proxies and/or IPv6 addresses. It holds *no account identity*.
- The **streamer** does playback from a stable datacenter IP with the
  OAuth-authenticated account. It never issues search-shaped traffic.

The resolver is disposable and untrusted; the streamer is stable and
holds the only credential worth protecting.

---

## 2. Why the source already supports this

Tracing youtube-source 1.18.2 shows loading and playback are **independent
rotations** over the configured client list, and each authentication
mechanism attaches to exactly one client family:

- **Loading** (`YoutubeAudioSourceManager.loadItemOnce`) iterates clients
  whose `canHandleRequest` accepts the identifier. `MUSIC` handles only
  `ytmsearch:`; the `NonMusicClient`s handle video/playlist/search.
- **Playback** (`YoutubeAudioTrack.process`) iterates every client with
  `supportsFormatLoading()` — i.e. `ClientOptions.playback`, default true —
  in config order, until one yields a working stream. `MUSIC` hard-overrides
  `supportsFormatLoading()` to `false`: it never plays.
- **OAuth** is injected into the HTTP context only when the attempting
  client returns `supportsOAuth() == true`. Only `Tv` overrides it. TV's
  `canHandleRequest` is `false`, so TV contributes *only* at playback:
  metadata must come from another client first (hence the existing
  `clientOptions: TV: playback: true` in our config).
- **PoToken** exists only as static fields on `Web` and `WebEmbedded`
  (`serviceIntegrityDimensions.poToken` in their Innertube context, plus a
  `pot` parameter appended to their playback URLs by
  `transformPlaybackUri`). No other client reads it.
- `Ios` / `AndroidVr` use neither mechanism; they ride on their native
  client profiles.

Resulting per-client matrix:

| Client      | Loads metadata | Plays | Auth path              |
|-------------|---------------|-------|------------------------|
| MUSIC       | music search  | never | none                   |
| TV          | no            | yes   | OAuth (only client)    |
| WEB         | yes           | yes   | PoToken                |
| WEBEMBEDDED | yes           | yes   | PoToken                |
| IOS         | yes           | yes   | none (native profile)  |
| ANDROID_VR  | yes           | yes   | none (native profile)  |

Two consequences:

1. **The README's "you do not need a poToken if using OAuth, and vice
   versa" is misleading for a mixed client list.** The mechanisms are not
   substitutes; each covers a different leg of the fallback chain. This is
   also why the single-node config keeps both.
2. **Resolution and playback can be assigned to different machines
   without forking anything**, because Lavalink's encoded track payloads
   are portable between nodes running the same source version. Load on
   node A, play the encoded track on node B — the standard multi-node
   Lavalink pattern.

---

## 3. Architecture

```
                         ┌──────────────────────────────┐
                         │         bot-template-rs       │
                         │  (MusicBackend: split impl)   │
                         └──────┬───────────────┬────────┘
              loadtracks only   │               │  play encoded track
                                ▼               ▼
              ┌────────────────────────┐  ┌────────────────────────┐
              │       RESOLVER          │  │        STREAMER         │
              │  clients: MUSIC, WEB,   │  │  clients: TV (+ §7)     │
              │  WEBEMBEDDED, IOS,      │  │  OAuth: ENABLED         │
              │  ANDROID_VR             │  │  PoT: unused            │
              │  OAuth: DISABLED        │  │  egress: datacenter IP  │
              │  PoT: bgutil, rotated   │  │  voice: Discord (DAVE)  │
              │  egress: proxy pool /   │  └────────────────────────┘
              │  IPv6 rotation          │
              └────────────────────────┘
```

### Resolver

- Clients: `MUSIC, WEB, WEBEMBEDDED, IOS, ANDROID_VR` (the current list
  minus TV). All are metadata-capable or search-capable; none needs an
  account.
- OAuth **disabled** — the account is never exposed on the dirty leg,
  even as a fallback.
- PoToken: still required for the WEB/WEBEMBEDDED legs. bgutil-pot lives
  here. Refresh via the plugin's live route (`POST /youtube` with
  `{"poToken", "visitorData", "refreshToken": "x"}` — the `"x"` sentinel
  leaves OAuth untouched) instead of the current
  rewrite-`application.yml`-and-restart cycle; the yaml values remain the
  cold-start seed. (This change is worth making even before the split —
  see the audit follow-ups.)
- Egress rotation: the plugin's route planner
  (`YoutubePluginLoader.getRoutePlanner`) supports `rotateonban`,
  `loadbalance`, `nanoswitch`, `rotatingnanoswitch` over CIDR blocks or
  an IPv6 block; note its `searchTriggersFail` option — upstream already
  treats search as the ban-triggering operation. A proxy pool fronts the
  node where raw IP blocks aren't available.
- LavaSrc stays here: mirroring (Spotify etc. → `ytsearch:`) is
  resolution work.
- No voice, no players of consequence; `/v4/loadtracks` is the product.

### Streamer

- Clients: `TV` first — the OAuth leg — plus whatever §7 decides about
  fallbacks.
- OAuth **enabled**, refresh token held only here. Token updates can also
  use the live `POST /youtube` route.
- Playback mechanics, honestly stated: playing an encoded track re-runs
  format loading on the streamer (one player-API call per track through
  the TV client, from the streamer's IP, with the account token), then
  fetches the stream from the same node. Format request and stream fetch
  therefore share an IP — no cross-IP stream-URL binding problem — and
  the request shape is a single authed playback call, not browse traffic.
- Voice/DAVE is entirely streamer-side and unaffected by the split
  (verified 2026-11-02: bot-template-rs supplies `channelId`; Lavalink
  4.2.2 terminates DAVE via koe/libdave).

### Shared services

- **yt-cipher**: both nodes make player requests (resolver at load time,
  streamer at playback time), so both need signature deciphering. It is a
  stateless HTTP service (`remoteCipher.url`); run one instance reachable
  by both, or one per node. No trust implications either way.
- **Admin panels**: one per node, or one panel parameterised by target
  node. The current panel's PoT/OAuth managers become resolver-side and
  streamer-side concerns respectively; the live `POST /youtube` route
  replaces their restart step in both cases.
- **docker-socket-proxy**: unchanged, per node host.

---

## 4. Client changes (bot-template-rs)

The template's `MusicBackend` trait is the seam; the split is a third
implementation beside the lavalink and native backends:

- Hold **two** `LavalinkClient` handles (resolver, streamer), each with
  its own `LavalinkConfig`.
- `play(query)`: `loadtracks` against the resolver; take the encoded
  track(s); `create_player_context` / update player on the streamer with
  the encoded payload.
- Search and playlist commands resolve against the resolver only.
  Playlists resolve to *N* encoded tracks — resolution cost concentrates
  on the resolver, which is the point.
- Queue state stays bot-side, as today; nodes remain interchangeable
  workers.
- **LavaSrc caveat:** LavaSrc performs its mirror search when a track
  *plays*, not when it loads — so handing the streamer a raw
  Spotify/LavaSrc encoded track would make the streamer search (with
  search disabled and TV unable to load, it fails cleanly, but it
  fails). The split backend must instead hand over the *already
  mirrored* YouTube track: when a resolver load returns a mirroring
  source's track, resolve its mirror on the resolver (the track info
  carries title/artist/ISRC — enough for the same `ytsearch:` providers
  LavaSrc itself would use) and pass that encoded track to the
  streamer.

CrackTunes integration, when it happens, inherits this design rather
than the single-node one.

---

## 5. Decisions

Made by this design:

- **D1. OAuth exists only on the streamer.** Never configured on the
  resolver, including "just as a fallback" — a fallback that fires is a
  credential on the dirty network.
- **D2. PoT exists only on the resolver.** The streamer gains nothing
  from it (its legs don't read it).
- **D3. Encoded tracks are the only interface between the legs.** No
  shared state, no shared database; either node can be rebuilt or
  replaced independently.

Open, with recommendations:

- **D4. Streamer fallback policy.** If TV fails on a track, the current
  chain would fall through to WEB/WEBEMBEDDED/IOS/VR — un-authed,
  browse-adjacent requests from the clean IP. *Recommendation:* streamer
  client list is `TV` only (optionally `TVHTML5_SIMPLY` once trialled),
  accepting a hard failure on tracks TV can't play rather than leaking
  the dirty pattern onto the clean leg. Revisit if the failure rate is
  measurable in practice.
- **D5. Resolver failure mode.** If all resolver egress is banned,
  searches fail but *already-queued playback continues* (streamer is
  independent). *Recommendation:* surface resolver health on the admin
  panel (extend the `/healthz` advisory pattern: cipher/pot are already
  advisory there) rather than failing over to resolving on the streamer.
  Resolving on the streamer "temporarily" is how the split dies.
- **D6. Resolver placement.** Co-located with the streamer behind a
  proxy pool, or a separate cheap VPS in front of residential egress.
  *Recommendation:* decide with the egress sourcing (§6); the node
  itself is nearly free (no voice, low CPU).

---

## 6. Open questions

- **Egress sourcing.** Mobile/residential proxy pool vs an IPv6 /64 (or
  several) on the host. The route planner covers the IPv6 case natively;
  the proxy case needs the pool to terminate in front of the node's
  HTTP layer. Cost and ban-rate differ by an order of magnitude; measure
  with the planner's ban signals before committing.
- **Rotation granularity.** `rotateonban` (reactive) vs per-request
  rotation. Reactive is quieter and matches upstream's intent.
- **Does search-result freshness suffer** if the resolver and streamer
  see different localisations? (Client `gl`/`hl` come from the fetched
  page config; expected negligible, worth one test.)
- **Metrics.** The split doubles the nodes to watch; the existing
  Prometheus endpoint (currently disabled) probably wants enabling on
  both, with per-node client-failure counters as the ban early-warning.

---

## 7. Migration path

1. **Phase 0 (independent, do first):** restart-free PoT/OAuth refresh
   via `POST /youtube` on the current single node. Removes the 6-hourly
   player drop regardless of the split.
2. **Phase 1:** clone the node into streamer configuration (clients
   trimmed per D4, OAuth on). Single-node bot still points at the old
   all-in-one node; the streamer idles as a spare.
3. **Phase 2:** stand up the resolver (OAuth off, planner/proxy egress,
   bgutil + PoT live-refresh). Point the bot's *search/load* calls at it
   behind a feature flag; playback unchanged.
4. **Phase 3:** move playback to the streamer (encoded-track handoff via
   the split `MusicBackend`). Decommission the all-in-one config — or
   keep it as the documented fallback for a single-host deployment.

Each phase is independently revertible, and phases 0–2 change nothing
about what listeners hear.
