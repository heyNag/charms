<!-- BEGIN GENERATED FROM SOURCE: packages/x-bookmarks/references/bird-fast.md -->
<!-- Do not edit directly; edit the source path and run make rebuild-generated. -->
<!-- END GENERATED FROM SOURCE -->

# Bird Backend Notes

Bird is the first-choice backend because it avoids paid X API credits by using
the user's existing X browser session and X web endpoints.

Sources:

```text
https://bird.fast/
https://github.com/steipete/bird
```

Do not install npm `bird-cli`; that package is unrelated to the `bird.fast`
project used here.

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
- Brave uses the Chrome-compatible profile directory, for example
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

In sandboxed agent environments, Keychain lookup may fail until retried through
an approved unsandboxed command path. If Bird still times out, prime access
while discarding the secret:

```sh
security find-generic-password -w -a Chrome -s "Chrome Safe Storage" "$HOME/Library/Keychains/login.keychain-db" >/dev/null
bird check --plain
```

Never print the Safe Storage password or X cookie values. Manual `auth_token`
and `ct0` should remain a last resort and only be used if the user explicitly
accepts that fallback.

Use read-only Bird commands by default. Do not tweet, reply, unbookmark, or
perform account-changing actions unless the user explicitly asks.
