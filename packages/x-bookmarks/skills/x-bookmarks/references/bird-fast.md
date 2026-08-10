# Bird Backend Notes

Bird is the first-choice backend because it avoids paid X API credits by using
the user's existing X browser session and X web endpoints.

Project documentation:

```text
https://bird.fast/
```

Install Bird through `https://bird.fast/` or the user's managed toolchain, then
verify the installed command with `bird --version`.

Bird behavior:

- No X API credits are required.
- No X Developer app is required.
- The user must be logged into `x.com` in a supported browser.
- macOS may ask for browser cookie or Keychain permission.
- X can break the backend by changing web client behavior.

Default checks:

```sh
bird --version
bird check --plain
bird whoami --plain
```

Default fetch:

```sh
scripts/fetch_bookmarks_bird.sh --count 25
```

Browser auth recovery:

- Open `https://x.com` in the user's default browser and ask the user to finish
  login there.
- Chrome: open `chrome://version`; the last folder in "Profile Path" is the
  profile name. Use it with
  `bird --cookie-source chrome --chrome-profile "PROFILE_NAME" check --plain`.
- If macOS asks for Keychain access, ask the user to allow it.
- If Chrome cookie extraction fails after login, ask the user to quit Chrome
  first and retry because the cookie database can be locked.
- Firefox uses `--cookie-source firefox --firefox-profile PROFILE_NAME`.
- On macOS, Brave uses the Chrome-compatible profile directory, for example
  `bird --cookie-source chrome --chrome-profile-dir "$HOME/Library/Application Support/BraveSoftware/Brave-Browser/Default" check --plain`.
- A confirmed browser profile can be persisted in app-owned local state at
  `~/.config/bird/config.json5`; do not commit it to this repo.

Chrome `Default` example:

```json5
{
  cookieSource: "chrome",
  chromeProfile: "Default",
}
```

If cookie metadata exists in Chrome but Bird still cannot authenticate, the
remaining issue is usually local decryption through macOS Keychain. Ask the user
to allow any Keychain prompt. If no prompt appears, ask the user to quit Chrome
completely and retry.

If Keychain access remains blocked, ask the user to run `bird check --plain` in
a normal terminal and approve the operating-system prompt. Never ask the user
to paste Safe Storage passwords or X cookie values into chat, commands, logs,
or agent-visible output.

Use read-only Bird commands by default. Do not tweet, reply, unbookmark, or
perform account-changing actions unless the user explicitly asks.
