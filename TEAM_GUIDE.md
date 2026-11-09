# PU Outreach — team guide (one page)

**What it does:** you screenshot a LinkedIn profile with ContactOut open → a row appears in the
*Automation* tab and a Gmail **draft** appears in *your* Gmail. You review and click Send yourself.
It never sends anything on its own.

## 1. Install (once, ~10 min)

| | Ubuntu / Linux | macOS (untested) | Windows (untested) |
|---|---|---|---|
| OCR | `sudo apt install tesseract-ocr libnotify-bin` | `brew install tesseract` | install from github.com/UB-Mannheim/tesseract/wiki |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | same | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| app | `git clone <repo-url> && cd pu-outreach && uv tool install .` | same | same |

(Private repo: ask Dev to add you on GitHub, or install from the zip: `uv tool install ./pu-outreach`.)

## 2. Your master draft (once)

In **your** BITS Gmail, make one draft (or copy Dev's text):
- Subject: `[PU-MASTER] Invitation - {{Company}} | BITS Pilani, Pilani Campus Placement Season 2026-27`
- First line: `{{Greeting}}` (instead of "Dear Team,")
- "We are excited to invite `{{Company}}` to participate…"
- Attach the JAF and the Placement Brochure. Leave **To** empty. Keep your signature.
- Type `{{…}}` in plain text (no bold inside; paste with Ctrl+Shift+V). Never send this draft.

## 3. Your web app (once, ~5 min)

1. Go to **script.google.com** → New project. Name it "PU Outreach drafter".
2. Project Settings (gear) → tick **Show "appsscript.json"**. Replace its content with `apps_script/appsscript.json`.
3. Replace `Code.gs` with `apps_script/Code.gs`. Put the sheet ID in `SHEET_ID`
   (the part between `/d/` and `/edit` in the sheet's URL). Save.
4. Choose `setupToken` in the function dropdown → **Run** → allow access → open
   **Execution log** and copy the token.
5. **Deploy → New deployment → Web app**: Execute as **Me**, Who has access **Anyone** → Deploy → copy the URL (ends in `/exec`).

*Why "Anyone"?* The app on your laptop must call it without a Google login. It's still
protected: without your secret token it refuses everything. Don't share the URL+token.
If BITS ever blocks "Anyone", tell Dev.

## 4. Connect (once)

```
pu-outreach setup        # paste URL + token
pu-outreach doctor --notify
```
Everything should show ✔. Each ✖ prints a fix.

**First, test on a COPY of the sheet:** File → Make a copy, put the copy's ID in `SHEET_ID`,
redeploy (Deploy → Manage deployments → edit → New version), and run one capture. When it
looks right, switch the ID back to the real sheet and redeploy.

## 5. Daily use

```
pu-outreach autostart enable     # starts at every login (or: pu-outreach run)
```
1. Open a LinkedIn profile, open the ContactOut panel so the email is visible.
   Keep the browser **not** fullscreen (the address bar must show).
2. Press **Alt+Print** (Windows: Win+PrtScn, macOS: Cmd+Shift+3).
3. A notification says: *draft ready* / *duplicate* (who and which row) / *not drafted* (why).
4. Open Gmail → Drafts → check the greeting and Remarks notes → **Send** (Mailtrack works as usual).

Stop it: `pu-outreach stop`. Remove autostart: `pu-outreach autostart disable`.
Wrong ma'am/sir? Fix the draft, and add the name to `names_override.json` (see README).
Problems: `pu-outreach doctor`, then `pu-outreach try <screenshot> --debug` and send the output to Dev.

## Rules
- Only for placement outreach. Don't copy contacts anywhere else.
- Someone asks to be removed → delete their row and their draft/mail; tell the team.
- Never edit the **Leads** tab with this tool; it doesn't touch it, and neither should you via it.
