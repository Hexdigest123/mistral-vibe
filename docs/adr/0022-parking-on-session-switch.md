# 0022 Parking a Running Session on a Session Switch

## Decision

A connection that attaches another session while the one it holds has turn work
(a running turn, a callback it waits on, queued turns) **parks** that session,
still running, instead of stopping it. This extends the parking a closed
channel's running session already gets (`vibe/app_server/_parked_sessions.py`,
ADR 0002) to a channel that stays open, and it amends ADR 0012: a client that
opts in no longer has to refuse a session switch until the turn ends.

- **Opt-in.** The client sends `initialize.capabilities.parkRunningSession:
  true` (`ClientCapabilities.park_running_session`, default `false`, ignored by
  an older server). Without it, or when the connection declared
  `agentPlugins`/`clientToolDefinitions`, whose runner stays bound to the first
  link, `session/start`, `session/resume` and `session/continue` replace the
  attached session as they always did. An idle session is never parked.
- **A runtime per running session.** A session reaches its client only through
  its `ChannelRuntime` (host adapter and link). Before the new session opens,
  the connection takes a fresh runtime from a *holder*, a twin `AppServer`
  built by the same factory (`AppServer._spawn_holder`), and the running
  session's runtime moves to the holder with the client identity, account and
  sign-in the connection has (`SwitchAway`). The holder has no transport:
  notifications and callbacks of the parked session are kept in its history,
  and its client requests fail as for a closed channel's. All runtimes of a
  process share its one Runtime host; a reference count in `HarnessProcess`
  lets only the last Host adapter shut that host down.
- **Registration.** The holder registers in `OpenSessions` like a closed
  channel's session, so `_stop_when_idle` stops it once its turn work ends, and
  a `session/resume` of it, from this connection or any other channel of the
  process, attaches it. A server that parks nothing on close (not multiplexed)
  keeps these in `background_sessions` and stops them when the connection
  closes, as quitting stopped the running turn before.
- **Attaching a parked session over a running one.** `session/resume` of a
  parked session by a connection that holds a session with turn work exchanges
  the two: the parked session's runtime is attached, the connection's moves to
  the holder that gave it up. The attach check that refused "a channel with a
  session" now only refuses connections that did not opt in. Open callbacks of
  the attached session are re-sent, its turn announced again with
  `turn/started`, and `interruptLeftTurn` applies as for any parked session.
- **Failure.** The new session is opened on the new runtime before the old one
  stops forwarding events. A failed open swaps the runtimes back and shuts the
  unused host down, so the client stays on its session.
- **Visibility.** A parked session is listed by `session/list` and read by
  `session/read` with its live status (`running`, `blocked`, then `idle`), so a
  client learns that a background turn ended by polling. Other connections see
  `session_busy` for a session a connection holds, unchanged; one it parked
  can be attached by any channel of the process.

## Consequences

- Parking is bounded by the sessions a client keeps running: each costs a Host
  adapter, not a Runtime host or process.
- A parked session cannot call its client's tools or start peers until it is
  attached again; such a call fails, as on a closed channel.
- Process-wide state a session needs (credentials, catalogs, org config) stays
  shared, per ADR 0019.
