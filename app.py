"""Rajasthan two-wheeler registrations — Streamlit dashboard on the Vahan data in Supabase.

Run locally:   streamlit run app.py
Secrets (.streamlit/secrets.toml or Streamlit Cloud > Settings > Secrets):
    SUPABASE_URL = "https://<project>.supabase.co"
    SUPABASE_ANON_KEY = "<anon / publishable key>"
Viewers only read data. "Refresh now" sits under Admin in the sidebar and needs the admin key,
which is checked inside Supabase (public.vahan_refresh_with_key); it is never stored in this app.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import vahan_logic as vl

IST = timezone(timedelta(hours=5, minutes=30))
st.set_page_config(page_title="Rajasthan 2W Registrations", page_icon="🛵", layout="wide")


# ---------------------------------------------------------------- data
# Public, read-only defaults for the "PPM-hub's Project" Supabase project. The anon key can only read
# the Vahan figures and call the key-protected refresh; secrets or environment variables override these.
DEFAULTS = {
    "SUPABASE_URL": "https://dcrnlittunfgaapptmwr.supabase.co",
    "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRjcm5saXR0dW5mZ2FhcHB0bXdyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg2OTU1NzUsImV4cCI6MjEwNDI3MTU3NX0.ngDiXC8H7tYNj9BG6h40dAfftVsGxj33-UH2OgAWxLE",
}


def _secret(name: str) -> str | None:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # noqa: BLE001 - no secrets file at all
        pass
    return os.environ.get(name) or DEFAULTS.get(name)


def _headers() -> dict:
    key = _secret("SUPABASE_ANON_KEY")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


@st.cache_data(ttl=900, show_spinner="Loading Vahan data from Supabase…")
def load_payload() -> dict:
    fixture = os.environ.get("VAHAN_FIXTURE")  # used by tests
    if fixture:
        with open(fixture, encoding="utf-8") as fh:
            return json.load(fh)
    r = requests.post(f"{_secret('SUPABASE_URL')}/rest/v1/rpc/vahan_app_data", headers=_headers(), json={}, timeout=60)
    r.raise_for_status()
    return r.json()


def start_refresh(admin_key: str) -> tuple[bool, str]:
    try:
        r = requests.post(f"{_secret('SUPABASE_URL')}/rest/v1/rpc/vahan_refresh_with_key", headers=_headers(),
                          json={"p_key": admin_key}, timeout=60)
    except requests.RequestException as e:
        return False, f"Couldn't reach Supabase: {e}"
    if r.status_code == 200:
        return True, f"Refresh started (run {r.json()}). It takes about 15 minutes; reload the data after that."
    if "not allowed" in r.text:
        return False, "That admin key isn't right."
    return False, f"Supabase refused the request ({r.status_code})."


# ---------------------------------------------------------------- formatting
def fmt(n) -> str:
    """Indian digit grouping: 12,34,567."""
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "—"
    n = int(round(n))
    s, neg = str(abs(n)), n < 0
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + s


def pct(x, signed=True) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)) or x is pd.NA:
        return "—"
    return f"{'+' if signed and x > 0 else ''}{x * 100:.1f}%"


_DROP = {"LTD", "LTD.", "LIMITED", "PVT", "PVT.", "PRIVATE", "(P)", "INDIA", "THE", "CO", "CO.", "COMPANY", "TECHNOLOGIES"}


def _cap(word: str) -> str:
    if word == "&" or any(ch.isdigit() for ch in word):
        return word
    core = word.strip("()")
    if len(core) <= 3:  # TVS, RTO, DTO, BMW, KTM
        return word.upper()
    return "-".join(p[:1].upper() + p[1:].lower() if not p.startswith("(") else "(" + p[1:2].upper() + p[2:].lower()
                    for p in word.split("-"))


def short_name(name: str, limit: int = 26) -> str:
    """'HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD' -> 'Honda Motorcycle & Scooter' (phone tables)."""
    import re as _re
    s = _re.sub(r"\(UNIT OF [^)]*\)", "", str(name)).replace(" AND ", " & ")
    words = [w for w in s.split() if w.upper() not in _DROP]
    s = " ".join(_cap(w) for w in words) or str(name)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def to_pct_col(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce") * 100


# ---------------------------------------------------------------- load
try:
    payload = load_payload()
except Exception as e:  # noqa: BLE001
    st.error(f"Couldn't load data from Supabase. Check SUPABASE_URL and SUPABASE_ANON_KEY in the app's secrets. ({e})")
    st.stop()

df = vl.build_frame(payload)
status = payload.get("status") or {}
prog = vl.progress_from(status, df)
offices = pd.DataFrame(payload.get("offices") or [])
now_ist = datetime.now(IST)
cur_fy = vl.fy_of(now_ist.year, now_ist.month)

# ---------------------------------------------------------------- phone or desktop layout
_ua = ""
try:
    _ua = st.context.headers.get("User-Agent", "") or ""
except Exception:  # noqa: BLE001
    pass
_is_phone = any(s in _ua for s in ("Mobi", "Android", "iPhone", "iPad"))

# ---------------------------------------------------------------- sidebar: admin
with st.sidebar:
    compact = st.toggle("Phone layout", value=_is_phone, help="Fewer columns, folded filters and tabs. Switches on by itself on phones.")
    st.subheader("Data")
    if status.get("last_refresh"):
        lr = datetime.fromisoformat(status["last_refresh"].replace("Z", "+00:00")).astimezone(IST)
        st.write(f"Vahan data refreshed **{lr:%d %b, %H:%M} IST**. Updates daily at 10:00 IST.")
    if status.get("jobs_left"):
        st.info(f"A refresh is running: {status['jobs_left']} offices to go.")
    diff = (status.get("portal_total") or 0) - (status.get("office_total") or 0)
    if diff == 0:
        st.success("RTO figures add up to Vahan's state total.")
    else:
        st.warning(f"RTO figures are {fmt(abs(diff))} {'short of' if diff > 0 else 'over'} Vahan's state total.")
    if st.button("Reload data", help="Fetch the latest stored figures from Supabase"):
        load_payload.clear()
        st.rerun()
    with st.expander("Admin"):
        key = st.text_input("Admin key", type="password", help="Only needed to start a fresh pull from Vahan.")
        if st.button("Refresh now", disabled=not key):
            ok, msg = start_refresh(key)
            (st.success if ok else st.error)(msg)

# ---------------------------------------------------------------- filters
if compact:
    st.markdown("### Rajasthan 2W registrations")
    if status.get("last_refresh"):
        _lr = datetime.fromisoformat(status["last_refresh"].replace("Z", "+00:00")).astimezone(IST)
        st.caption(f"Vahan data as of {_lr:%d %b, %H:%M} IST · 2WN + 2WT + 2WIC")
else:
    st.title("Rajasthan two-wheeler registrations")
    st.caption("Vahan 4 · Two-wheelers (2WN + 2WT + 2WIC) · by RTO, manufacturer and fuel")

_picked = sum(bool(st.session_state.get(n)) for n in ("f_hub", "f_town", "f_rto", "f_month", "f_fuel"))
if compact:
    _box = st.expander(f"Filters{f' · {_picked} in use' if _picked else ''}", expanded=False)
    _r1, _r2, _r3 = _box.columns(2), _box.columns(2), _box.columns(2)
    c = [_r1[0], _r1[1], _r2[0], _r2[1], _r3[0], _r3[1]]
else:
    c = st.columns(6)
hubs = c[0].multiselect("Hub", sorted(offices["hub"].unique()) if len(offices) else [], placeholder="All hubs", key="f_hub")
town_opts = sorted(offices[offices["hub"].isin(hubs) | (not hubs)]["town"].unique()) if len(offices) else []
towns = c[1].multiselect("Town", town_opts, placeholder="All towns", key="f_town")
rto_rows = offices[(offices["hub"].isin(hubs) | (not hubs)) & (offices["town"].isin(towns) | (not towns))].sort_values("office") if len(offices) else offices
rto_labels = {r.code: f"{r.office} ({r.code})" for r in rto_rows.itertuples()}
rtos = c[2].multiselect("RTO", list(rto_labels), format_func=lambda k: rto_labels.get(k, k), placeholder="All RTOs", key="f_rto")
fy_opts = sorted(df["fy"].unique().tolist(), reverse=True)
fys = c[3].multiselect("Year", fy_opts, default=[cur_fy] if cur_fy in fy_opts else fy_opts[:1], format_func=lambda y: f"FY {y % 100:02d}-{(y + 1) % 100:02d}", placeholder="All years", key="f_fy")
months = c[4].multiselect("Month", vl.FY_MONTHS, format_func=lambda m: vl.MONTH_NAMES[m], placeholder="All months", key="f_month")
fuel_opts = df.groupby("fuel")["regs"].sum().sort_values(ascending=False).index.tolist()
fuels = c[5].multiselect("Fuel", fuel_opts, placeholder="All fuels", key="f_fuel")

f = vl.Filters(hubs=hubs, towns=towns, rtos=rtos, fys=fys, months=months, fuels=fuels)
d = vl.Dash(df, f, prog)
k = d.kpi()
makers = d.makers()

# ---------------------------------------------------------------- headline
place = (", ".join(rto_labels.get(r, r) for r in rtos) if 0 < len(rtos) <= 2 else f"{len(rtos)} RTOs" if rtos
         else ", ".join(towns) if 0 < len(towns) <= 2 else f"{len(towns)} towns" if towns
         else ", ".join(hubs) + " hub" + ("s" if len(hubs) > 1 else "") if 0 < len(hubs) <= 2 else f"{len(hubs)} hubs" if hubs
         else "Rajasthan")
years = " + ".join(vl.fy_label(y) for y in d.fys)
pm_name = vl.month_label(prog.month) if prog.month else ""
ly_fy = vl.fy_label(d.fys[0] - 1) if d.fys else ""
lede = f"**{place}, {years}{', ' + ', '.join(fuels) if fuels else ''}:** {fmt(k['regs'])} registrations"
if k["change"] is not None:
    lede += f", **{pct(k['change'])}** on the same months of {ly_fy}"
    if k["pm_in"]:
        lede += f" (**{pct(k['change_pr'])}** with {pm_name} at pro-rata)"
else:
    lede += " (no comparison: " + ("pick a single year to compare" if k["no_cmp"] == "multi" else f"{ly_fy} is not loaded") + ")"
if len(makers):
    lede += f". {makers.iloc[0]['maker']} leads with {pct(makers.iloc[0]['share'], False)}."
st.markdown(lede)

mom_title = f"{vl.month_label(k['focus'])} vs {vl.month_label(k['prev'])}" if k["focus"] else "Growth over last month"
if k["mom"] is not None:
    mom_detail = (f"{fmt(k['fm'])} to date ({fmt(k['fm_pr'])} pro-rata) vs {fmt(k['prev_v'])}" if k["focus_in_progress"]
                  else f"{fmt(k['fm'])} vs {fmt(k['prev_v'])}")
else:
    mom_detail = f"{vl.month_label(k['prev'])} is not loaded" if k["prev"] else "No months selected"
span = "" if not k["first"] else vl.month_label(k["first"]) if k["first"] == k["last"] else f"{vl.month_label(k['first'])} – {vl.month_label(k['last'])}"
if compact:
    import html as _h

    def _chg(x):
        if x is None:
            return "—"
        col = "#15803d" if x > 0 else "#b91c1c" if x < 0 else "inherit"
        return f'<span style="color:{col}">{pct(x)}</span>'

    cards = [
        ("Registrations", fmt(k["regs"]), span + (f"<br>Pro-rata {fmt(k['regs_pr'])}" if k["pm_in"] else "")),
        ("YoY growth", _chg(k["change"]),
         (f"Pro-rata {_chg(k['change_pr'])}<br>" if k["pm_in"] and k["change"] is not None else "")
         + (f"{fmt(k['regs'])} vs {fmt(k['regs_ly'])}" if k["change"] is not None else ("Pick one year" if k["no_cmp"] == "multi" else f"{ly_fy} not loaded"))),
        (mom_title, _chg(k["mom"]),
         (f"Pro-rata {_chg(k['mom_pr'])}<br>" if k["focus_in_progress"] and k["mom"] is not None else "") + mom_detail),
        (f"{pm_name} pro-rata" if k["pm_in"] else "Month in progress", fmt(k["pm_pr"]) if k["pm_in"] else "—",
         (f"{fmt(k['pm_mtd'])} in {prog.elapsed}/{prog.days} days" + (f"<br>vs {fmt(k['pm_ly'])}: {_chg(k['pm_change_pr'])}" if k["pm_ly"] else "")) if k["pm_in"] else "Not in selection"),
        ("Top manufacturer", pct(makers.iloc[0]["share"], False) if len(makers) else "—",
         _h.escape(short_name(makers.iloc[0]["maker"], 28)) if len(makers) else ""),
    ]
    st.markdown(
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:4px 0 8px">'
        + "".join(
            f'<div style="border:1px solid rgba(128,128,128,.3);border-radius:10px;padding:10px 12px;min-width:0{";grid-column:span 2" if i == len(cards) - 1 and len(cards) % 2 else ""}">'
            f'<div style="font-size:.78rem;opacity:.75">{_h.escape(lab)}</div>'
            f'<div style="font-size:1.45rem;font-weight:600;line-height:1.25;font-variant-numeric:tabular-nums">{val}</div>'
            f'<div style="font-size:.74rem;opacity:.75;line-height:1.35">{sub}</div></div>'
            for i, (lab, val, sub) in enumerate(cards))
        + "</div>", unsafe_allow_html=True)
else:
    m1, m2, m5, m3, m4 = st.columns(5)
    m1.metric("Registrations", fmt(k["regs"]), help=f"{span}" + (f"; {pm_name} to {prog.elapsed} {vl.MONTH_NAMES[int(prog.month[5:])]}" if k["pm_in"] else ""))
    if k["pm_in"]:
        m1.caption(f"{span} · pro-rata total {fmt(k['regs_pr'])}")
    else:
        m1.caption(span)
    m2.metric("YoY growth", pct(k["change"]), delta=f"pro-rata {pct(k['change_pr'])}" if k["pm_in"] and k["change"] is not None else None, delta_color="off")
    m2.caption(f"{fmt(k['regs'])} vs {fmt(k['regs_ly'])}" if k["change"] is not None else "Pick a single year to compare" if k["no_cmp"] == "multi" else f"{ly_fy} is not loaded")
    if k["pm_in"]:
        m3.metric(f"{pm_name} at pro-rata", fmt(k["pm_pr"]), delta=pct(k["pm_change_pr"]) if k["pm_change_pr"] is not None else None)
        m3.caption(f"{fmt(k['pm_mtd'])} so far over {prog.elapsed} of {prog.days} days" + (f" · {vl.MONTH_NAMES[int(prog.month[5:])]} {int(prog.month[:4]) - 1}: {fmt(k['pm_ly'])} ({pct(k['pm_change'])} to date)" if k["pm_ly"] else ""))
    else:
        m3.metric("Month in progress at pro-rata", "—")
        m3.caption("The month in progress isn't in the selected years or months.")
    m5.metric(mom_title, pct(k["mom"]), delta=f"pro-rata {pct(k['mom_pr'])}" if k["focus_in_progress"] and k["mom"] is not None else None, delta_color="off",
              help="Latest selected month against the month before it. A month still running counts to date; pro-rata scales it to a full month.")
    m5.caption(mom_detail)
    if len(makers):
        m4.metric("Top manufacturer", f"{pct(makers.iloc[0]['share'], False)} share")
        m4.caption(f"{makers.iloc[0]['maker']} · {fmt(makers.iloc[0]['regs'])} registrations")


# ---------------------------------------------------------------- month by month
def month_chart():
    st.subheader("Month by month")
    t = d.trend()
    fy_main = int(t["fy"].iloc[0]) if len(t) else cur_fy
    colors = ["rgba(37,99,235,%s)" % (0.45 if r.in_progress else 1 if r.picked else 0.3) for r in t.itertuples()]
    fig = go.Figure()
    labels = [("≈" + fmt(r.regs_pr)) if r.in_progress and r.regs_pr else (fmt(r.regs) if r.regs is not None else "") for r in t.itertuples()]
    fig.add_bar(x=t["label"], y=t["regs"], name=vl.fy_label(fy_main), marker_color=colors,
                text=None if compact else labels, textposition="outside", cliponaxis=False,
                hovertemplate="%{x}: %{y:,}<extra></extra>")
    fig.add_scatter(x=t["label"], y=t["regs_ly"], name=vl.fy_label(fy_main - 1), mode="lines+markers", line=dict(color="#6b7280", width=2))
    for r in t.itertuples():
        if r.in_progress and r.regs_pr:
            i = list(t["label"]).index(r.label)
            fig.add_shape(type="rect", x0=i - 0.4, x1=i + 0.4, y0=0, y1=r.regs_pr, line=dict(color="rgba(37,99,235,1)", dash="dash", width=1.5))
    fig.update_layout(height=260 if compact else 360, margin=dict(l=4, r=4, t=30, b=4),
                      legend=dict(orientation="h", y=1.15), bargap=0.25 if compact else 0.3,
                      yaxis=dict(title=None, gridcolor="rgba(128,128,128,0.2)", tickformat="~s"), xaxis=dict(title=None, tickangle=0),
                      dragmode=False)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "scrollZoom": False})
    st.caption("Bars: latest selected FY. Line: the year before. The month in progress is pale to date, with a dashed outline at pro-rata.")


# ---------------------------------------------------------------- tables
cfg = {
    "rank": st.column_config.NumberColumn("#", width="small"),
    "regs": st.column_config.NumberColumn("Registrations", format="localized"),
    "regs_ly": st.column_config.NumberColumn("Last FY*", format="localized"),
    "regs_pr": st.column_config.NumberColumn("Pro-rata", format="localized"),
    "share": st.column_config.ProgressColumn("Share", format="%.1f%%", min_value=0, max_value=100,
                                             help="Market share: registrations ÷ total registrations for the filters applied"),
    "change": st.column_config.NumberColumn("YoY*", format="%+.1f%%", help="Growth over the same months of the previous FY"),
    "change_pr": st.column_config.NumberColumn("YoY (pro-rata)", format="%+.1f%%", help="Same, with the month in progress at pro-rata"),
    "mom": st.column_config.NumberColumn("MoM", format="%+.1f%%", help="Growth of the latest selected month over the month before"),
    "mom_pr": st.column_config.NumberColumn("MoM (pro-rata)", format="%+.1f%%", help="Same, with the month in progress at pro-rata"),
}
cfg_phone = {  # same columns as desktop, tighter labels and numbers
    "rank": st.column_config.NumberColumn("#", width=34, pinned=True),
    "regs": st.column_config.NumberColumn("Regs", format="localized"),
    "regs_ly": st.column_config.NumberColumn("Last FY*", format="localized"),
    "share": st.column_config.NumberColumn("Share", format="%.1f%%", help="Registrations ÷ total for the filters applied"),
    "change": st.column_config.NumberColumn("YoY*", format="%+.1f%%"),
    "change_pr": st.column_config.NumberColumn("YoY (pro-rata)", format="%+.1f%%"),
    "mom": st.column_config.NumberColumn("MoM", format="%+.1f%%"),
    "mom_pr": st.column_config.NumberColumn("MoM (pro-rata)", format="%+.1f%%"),
}


def show(table: pd.DataFrame, cols: list[str], names: dict, fname: str, select_key: str | None = None):
    """Every column on desktop and phone; the name column (and rank) stays frozen while scrolling sideways,
    and the header row stays frozen while scrolling down."""
    if compact and cols[0] == "office_code":  # on a phone the RTO name is the frozen column
        cols = ["office", "office_code"] + [c_ for c_ in cols if c_ not in ("office", "office_code")]
    name_col = next(c_ for c_ in cols if c_ in names and c_ != "office_code") if cols[0] == "office_code" else (cols[1] if cols[0] == "rank" else cols[0])
    out = table[cols].copy()
    for c_ in ("share", "change", "change_pr", "mom", "mom_pr"):
        if c_ in out:
            out[c_] = to_pct_col(out[c_])
    csv = out.to_csv(index=False).encode("utf-8")
    if compact and name_col in ("maker", "office"):
        out[name_col] = out[name_col].map(lambda s_: short_name(s_, 20))
    text_cols = {k_: st.column_config.TextColumn(v, pinned=(k_ == name_col), width=(118 if compact and k_ == name_col else None))
                 for k_, v in names.items()}
    conf = {**cfg, "rank": st.column_config.NumberColumn("#", width="small", pinned=True), **(cfg_phone if compact else {}), **text_cols}
    extra = dict(on_select="rerun", selection_mode="single-row", key=select_key) if select_key else {}
    event = st.dataframe(out, column_config=conf, hide_index=True, width="stretch",
                         height=min(480, 38 + 35 * max(len(out), 1)), **extra)
    st.download_button("Download CSV", csv, file_name=fname, mime="text/csv", key=f"dl-{fname}")
    return event


def fuel_section():
    st.subheader("By fuel")
    show(d.by_fuel(), ["fuel", "regs", "share", "regs_ly", "change", "change_pr", "mom", "mom_pr"], {"fuel": "Fuel (Vahan name)"}, "vahan_by_fuel.csv")


def hub_section():
    st.subheader("By hub")
    st.caption("All hubs for the selected years, months and fuels.")
    show(d.by_hub(), ["hub", "regs", "share", "regs_ly", "change", "change_pr", "mom", "mom_pr"], {"hub": "Hub"}, "vahan_by_hub.csv")


def maker_section():
    st.subheader("Manufacturers")
    show(makers, ["rank", "maker", "regs", "share", "regs_ly", "change", "change_pr", "mom", "mom_pr"], {"maker": "Manufacturer"}, "vahan_by_manufacturer.csv")


@st.cache_data(ttl=900, show_spinner="Building the RTO × maker file…")
def all_rto_makers_csv(_d, key: tuple) -> bytes:
    t = _d.all_rto_makers()
    if not len(t):
        return b""
    t = t[["office_code", "office", "town", "hub", "rank", "maker", "regs", "share", "regs_ly", "change", "change_pr", "mom", "mom_pr"]].copy()
    for c_ in ("share", "change", "change_pr", "mom", "mom_pr"):
        t[c_] = (pd.to_numeric(t[c_], errors="coerce") * 100).round(2)
    return t.rename(columns={"rank": "rank_in_rto", "share": "share_in_rto_%", "change": "yoy_%", "change_pr": "yoy_prorata_%",
                             "mom": "mom_%", "mom_pr": "mom_prorata_%"}).to_csv(index=False).encode("utf-8")


def rto_section():
    st.subheader("By RTO")
    rto_t = d.by_rto()
    st.caption("Tap a row (or pick an RTO below) to see every manufacturer in that RTO.")
    event = show(rto_t, ["office_code", "office", "town", "hub", "regs", "share", "regs_ly", "change", "change_pr", "mom", "mom_pr"],
                 {"office_code": "Code", "office": "RTO", "town": "Town", "hub": "Hub"}, "vahan_by_rto.csv", select_key="rto_table")

    codes = rto_t["office_code"].tolist()
    names_ = dict(zip(rto_t["office_code"], rto_t["office"]))
    rows = list(event.selection.rows) if event is not None and hasattr(event, "selection") else []
    picked_row = codes[rows[0]] if rows and rows[0] < len(codes) else None
    if picked_row != st.session_state.get("_rto_row_prev"):  # a new row tap updates the dropdown
        st.session_state["_rto_row_prev"] = picked_row
        if picked_row:
            st.session_state["rto_drill"] = picked_row
    if st.session_state.get("rto_drill") not in codes:
        st.session_state["rto_drill"] = None
    choice = st.selectbox("Manufacturers in RTO", [None] + codes, key="rto_drill",
                          format_func=lambda c_: "Pick an RTO…" if c_ is None else f"{names_.get(c_, c_)} ({c_})")
    if choice:
        st.markdown(f"**Manufacturers in {names_.get(choice, choice)} ({choice})**")
        show(d.rto_makers(choice), ["rank", "maker", "regs", "share", "regs_ly", "change", "change_pr", "mom", "mom_pr"],
             {"maker": "Manufacturer"}, f"vahan_makers_{choice}.csv")
        st.caption("Share here is within this RTO. Year, month and fuel filters apply.")

    key = (tuple(hubs), tuple(towns), tuple(rtos), tuple(d.fys), tuple(months), tuple(fuels), status.get("last_refresh"))
    data = all_rto_makers_csv(d, key) if st.toggle("Prepare all RTOs × manufacturers for download", key="rto_all_toggle") else b""
    if data:
        st.download_button("Download all RTOs × manufacturers (CSV)", data, file_name="vahan_rto_x_manufacturer.csv",
                           mime="text/csv", key="dl-rto-x-maker")


if compact:
    tab_trend, tab_makers, tab_rto, tab_mix = st.tabs(["Trend", "Makers", "RTOs", "Fuel & hub"])
    with tab_trend:
        month_chart()
    with tab_makers:
        maker_section()
    with tab_rto:
        rto_section()
    with tab_mix:
        fuel_section()
        hub_section()
    st.caption(f"Share = market share within the filters applied. YoY = vs the same months of last FY. MoM = {mom_title}. "
               f"(pro-rata) columns count {pm_name} at its daily average so far. Swipe tables sideways for every column; "
               "the name column and headings stay in place.")
else:
    month_chart()
    fuel_section()
    hub_section()
    maker_section()
    rto_section()

st.caption(f"MoM = growth of {vl.month_label(k['focus']) if k['focus'] else 'the latest selected month'} over the month before; "
           "a month still running counts to date, and MoM (pro-rata) scales it to a full month. "
           "* Same months of the previous FY; the month in progress counts to date against the full month last year. "
           f"Pro-rata scales {pm_name} to a full month: to date ÷ {prog.elapsed} × {prog.days}. "
           "Change is shown only when one year is picked.")

with st.expander("How these numbers are built"):
    st.markdown(
        "- **Source:** Vahan 4 dashboard (MoRTH), Maker × Month report for Rajasthan, run separately for every RTO/DTO and fuel type, "
        "pulled into Supabase daily at 10:00 IST.\n"
        "- **Two-wheelers** = 2WN (non-transport) + 2WT (transport) + 2WIC (invalid carriage).\n"
        "- **Financial year** runs April–March.\n"
        "- **Fuel** names are Vahan's own; PURE EV and ELECTRIC(BOV) are both battery-electric.\n"
        "- **Town and Hub** come from your office mapping.\n"
        "- Every month is checked against Vahan's own state-wide total (see the sidebar).")
