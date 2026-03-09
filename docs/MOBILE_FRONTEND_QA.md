# TYXT Mobile Frontend QA Checklist

This checklist is for real-phone verification of `third_party/tyxt_mobile_frontend`.

## 1) Pre-check

1. Backend running and reachable from phone.
2. `/health` is accessible from the phone browser.
3. If using login/session across domains, both frontend and backend must be HTTPS.

## 2) Recommended deployment modes

### Mode A (Recommended): Same origin

- Frontend and backend under the same origin.
- Example:
  - frontend: `https://agent.example.com/mobile/`
  - API base: `https://agent.example.com/v1`
- This has the best session-cookie compatibility.

### Mode B: Cross origin with cookie session

- Frontend and backend are different origins.
- Require:
  - HTTPS on both sides
  - `SESSION_COOKIE_SAMESITE=None`
  - `SESSION_COOKIE_SECURE=True`
- In mobile UI API settings, keep `Use Cookie Session` enabled.

### Mode C: Cross origin without cookie session (fallback)

- In mobile UI API settings, disable `Use Cookie Session`.
- App can still work by sending `user_id` metadata and local cached user state.
- Some server-side session-dependent behaviors may be limited.

## 3) Mobile test flow

1. Open mobile frontend and configure API URL/model.
2. Login with test account.
3. Send a short message and verify:
   - stream appears immediately by chunks
   - stop button works
4. Verify session sync:
   - create/select session in mobile
   - open same user in WebUI and check context continuity
5. Verify profile/persona/memory:
   - update nickname/profile
   - update persona (admin account)
   - add memory strip and save
6. Verify TTS:
   - click speaker icon on assistant message
   - audio file plays in browser
7. Switch network (Wi-Fi -> 5G) and retry one message.

## 4) Pass criteria

- Login succeeds and remains usable after page refresh.
- Streaming output is smooth and not character-throttled.
- Session list/load/rename/delete all work.
- Memory strips save and can be reloaded.
- TTS endpoint returns playable audio.

## 5) Common issues

- Login works once but lost after refresh:
  - usually cookie policy issue (cross-origin + SameSite).
  - use Mode A or configure Mode B.
- No response on chat request:
  - check API base URL path (`/v1`).
  - check CORS and reverse-proxy headers.
- TTS returns success but no sound:
  - check audio autoplay policy and output device permission.
