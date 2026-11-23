# Rajasthan 2W Registrations — Streamlit app

Same dashboard as the Claude version, but it runs without Claude: it reads the Vahan data that
Supabase collects every day at 10:00 IST (that part already runs on its own).

Filters: Hub, Town, RTO, Year (FY), Month, Fuel — all multi-select; empty = all.
Shows: registrations, change vs last FY (current month to date vs full month last year),
pro-rata for the month in progress (to date ÷ day of latest pull × days in month),
month-by-month chart, and tables by fuel, hub, manufacturer and RTO (each downloadable as CSV).

## Run on your computer (Windows)
1. Install Python 3.10+ from python.org (tick "Add Python to PATH").
2. Double-click `Run_Vahan_App.bat`. First run installs everything (a few minutes);
   the app opens at http://localhost:8501.
   Others on your office network can open http://<your-PC-name>:8501 while it runs.

## Put it online for your team (free, Streamlit Community Cloud)
1. Create a GitHub repository and upload these files **except `ADMIN_KEY.txt`**
   (and `.streamlit/secrets.toml` if the repository is public).
2. Go to https://share.streamlit.io → Create app → pick the repository, main file `app.py`.
3. Advanced settings → Secrets: paste the two lines from `.streamlit/secrets.toml`.
4. Deploy, then share the app link. Under Settings → Sharing you can make it public or
   limit it to the email addresses you invite.

## On a phone
The app switches to a phone layout by itself on mobiles: filters fold into one "Filters" panel,
the four headline figures sit in a 2 x 2 grid, and Trend / Makers / RTOs / Fuel & hub are tabs.
Phone tables show name, registrations, share and the change that matters most (with the month in
progress at pro-rata when it's included). Use the "Phone layout" switch in the menu (top left) to
change layouts by hand.

To get an app icon: open the app link in Chrome (Android) or Safari (iPhone) →
Share / menu → **Add to Home Screen**. It then opens full-screen like an app.
(This needs the online version from Streamlit Community Cloud, or your PC's address on the same Wi-Fi.)

## Viewers vs admin
Everyone can view, filter and download. **Refresh now** (sidebar → Admin) needs the key in
`ADMIN_KEY.txt`; Supabase checks it, the app never stores it. Viewers without the key cannot
start a pull. The daily 10:00 IST refresh runs regardless.

## Notes
- Data is cached for 15 minutes; "Reload data" in the sidebar fetches the latest at once.
- The anon key in secrets.toml is Supabase's public key: it can only read the Vahan figures and
  call the key-protected refresh.
