# OpenClaw + Tailscale Setup

## Accounts and installation

- OpenClaw did not require a separate OpenClaw account.
- Tailscale was set up with **Sign in with Apple**.
- Both the Mac and iPhone must use the same Tailscale account and tailnet.

### Mac

Install the OpenClaw and Tailscale apps with Homebrew:

```bash
brew update
brew install --cask openclaw
brew install --cask tailscale-app
```

Launch both apps. In OpenClaw, select **This Mac** and let the app install its
matching CLI and gateway runtime. In Tailscale, sign in with Apple and enable
its CLI integration if prompted.

### iPhone

Install both **OpenClaw** and **Tailscale** from the App Store. Open Tailscale,
sign in with the same Apple account used on the Mac, allow the VPN
configuration, and connect.

## Fix the OpenClaw CLI path

The app installed the CLI under `~/.openclaw/bin`, but that directory was not
initially on the shell `PATH`.

Verify the CLI exists:

```bash
ls -l ~/.openclaw/bin/openclaw
```

Add it to the `PATH` and reload the shell:

```bash
echo 'export PATH="$HOME/.openclaw/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
openclaw --version
```

## Authenticate the model

Authenticate OpenClaw with the existing OpenAI account:

```bash
openclaw models auth login --provider openai
```

OpenClaw itself did not require a separate account.

## Configure the gateway and Tailscale Serve

Keep command execution approval-gated, bind the OpenClaw gateway to the Mac's
loopback interface, and expose it only inside the tailnet through Tailscale
Serve:

```bash
openclaw config set tools.exec.mode ask
openclaw gateway restart
openclaw config set gateway.bind loopback
openclaw config set gateway.tailscale.mode serve
openclaw gateway restart
```

The resulting gateway configuration was:

```text
Gateway: 127.0.0.1:18789
Tailscale mode: serve
```

If OpenClaw reports that `tailscale serve` failed, give the current macOS user
permission to manage the Tailscale configuration:

```bash
sudo tailscale set --operator="$USER"
```

Then enable or test Serve directly:

```bash
tailscale serve --bg --yes 18789
```

## Verify access

Check both services on the Mac:

```bash
openclaw gateway status
tailscale serve status
```

`tailscale serve status` should show a tailnet-only HTTPS address proxying to
the local gateway, for example:

```text
https://rohitmacmini.taildc2a5d.ts.net
└── proxy http://127.0.0.1:18789
```

Open that HTTPS address in Safari on the iPhone. It initially failed because the
iPhone was not logged in to Tailscale. Signing in to the Tailscale app on the
iPhone with the same account/tailnet fixed access.

Once Safari can reach the address, leave Tailscale connected and use the
OpenClaw iPhone app to connect or scan the gateway pairing code.

## Test the gateway

Send this prompt from OpenClaw:

```text
Reply with exactly: openclaw-gateway-ok
```

The response was exactly:

```text
openclaw-gateway-ok
```

This confirmed that the iPhone, Tailscale Serve, OpenClaw gateway, and OpenAI
model connection were working.

## Configure guarded Mac command execution

Bind execution to the Mac node and retain per-command approval:

```bash
openclaw config set tools.exec.host node
openclaw config set tools.exec.node "<MAC-NODE-ID-OR-NAME>"
openclaw config set tools.exec.mode ask
openclaw gateway restart
```

Replace `<MAC-NODE-ID-OR-NAME>` with the Mac node identifier reported by
OpenClaw.

## Remote command tests

### Test 1: command denied

Prompt:

```text
Run /usr/bin/uname -n on my Mac and return only stdout.
Do not execute any other command.
```

OpenClaw created an approval request for `/usr/bin/uname -n`, but the final
result was:

```text
Exec denied (..., user-denied): /usr/bin/uname -n
```

The command did not run and produced no new output.

The cause was later found in the native OpenClaw Mac app: **Command access** was
set to **Deny**. The Mac node's local approval policy overrides or narrows the
gateway's requested execution policy, so `tools.exec.mode ask` alone was not
sufficient.

### Test 2: execution-host mismatch

The same prompt was tested in a new chat. The execution tool requested
`host: "auto"`, while OpenClaw was configured to require the Mac node:

```text
exec host not allowed (requested auto; configured host is node;
set tools.exec.host=auto to allow this override).
```

The command again did not run. This test exposed a mismatch between the
requested execution host (`auto`) and the configured host (`node`).

## Fix approval-gated command execution

Open the native OpenClaw Mac app settings:

```text
OpenClaw menu
→ Settings
→ Exec Approvals
```

The initial native policy was:

```text
Command access: Deny
Prompt behavior: Ask on Allowlist Miss
Fallback when unreachable: Deny
```

Change only **Command access** from **Deny** to **Allowlist**. Keep the other
settings unchanged:

```text
Command access: Allowlist
Prompt behavior: Ask on Allowlist Miss
Fallback when unreachable: Deny
```

The resulting effective policy was verified as:

```text
Host: node
Security: allowlist
Ask: on-miss
Fallback: deny
Allowlist entries: 0
```

With no trusted commands in the allowlist, each new command requires an approval
prompt. If the approval UI is unavailable or the request expires, the command is
denied.

## Successful remote command test

OpenClaw displayed a native approval prompt for:

```text
/bin/sh -lc "/bin/echo openclaw-remote-ok"
```

After selecting **Allow Once**, the command ran successfully. This confirmed
approval-gated remote command execution on the Mac without permanently trusting
the command.

## Upgrade the macOS app and gateway

The Homebrew cask upgrades only `OpenClaw.app`. The app-managed CLI and gateway
are installed separately under `~/.openclaw`, so upgrade them independently:

```bash
brew upgrade --cask openclaw
command -v openclaw
openclaw --version
openclaw update
```

If the update cannot enter maintenance, stop the gateway through launchd before
retrying. Prefer this over killing the process directly:

```bash
openclaw gateway stop
openclaw update
```

An update can replace the package successfully and then fail during its embedded
Doctor run with this message:

```text
The update parent owns Gateway activation.
```

First confirm that `openclaw --version` reports the new version. Then complete
the repair outside the updater and refresh the LaunchAgent definition:

```bash
openclaw gateway stop
openclaw doctor --fix
openclaw gateway install --force
openclaw gateway status --deep
openclaw health
```

If the gateway status and logs show that it is running and ready, but the app
still reports **The update is installed, but Gateway health did not become
ready**, the app may be retaining a failed post-update receipt. Quit OpenClaw
completely, remove only that receipt, and relaunch:

```bash
defaults delete ai.openclaw.mac openclaw.postAppUpdateReceipt
open -a OpenClaw
```

Do not clear the receipt until gateway health has been verified; otherwise it
can hide a real startup failure.

## Current status

The OpenClaw gateway, OpenAI model connection, Tailscale Serve connection, and
iPhone access are working. The simple gateway prompt passed. Approval-gated
remote Mac command execution also passed after correcting the Mac app's native
Exec Approvals policy from **Deny** to **Allowlist** and approving the test
command with **Allow Once**.
