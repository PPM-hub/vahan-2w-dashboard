"""Calculations for the Vahan Rajasthan two-wheeler dashboard (no Streamlit here, so it can be tested).

Data comes from the Supabase function public.vahan_app_data():
  rows: [month 'YYYY-MM', office_code, maker, fuel, registrations]
  offices: [{code, office, town, hub}]
  status: {last_refresh, data_date 'YYYY-MM-DD' (IST date of the latest Vahan pull), jobs_left, portal_total, office_total}

Rules (same as the Claude dashboard):
- Financial year runs April-March; FY 2026 = Apr 2026 - Mar 2027.
- Every filter is a list; an empty list means "all".
- Change vs last FY needs exactly one FY picked. It compares the selected months with the same
  months a year earlier; the month in progress counts to date against the full month last year.
- Pro-rata: the month in progress (month of the latest pull) is scaled to a full month at its
  daily average so far: to-date / day of the pull x days in month (e.g. 23 Nov: / 23 x 30).
- Growth over last month (MoM): the latest selected month vs the calendar month before it
  (whatever the month filter). If the latest month is in progress it counts to date, and
  "MoM pro-rata" uses its pro-rata figure instead.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

import pandas as pd

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]


def fy_label(fy: int) -> str:
    return f"FY {fy}-{(fy + 1) % 100:02d}"


def month_label(key: str) -> str:
    y, m = key.split("-")
    return f"{MONTH_NAMES[int(m)]} {y}"


def fy_of(year: int, month: int) -> int:
    return year if month >= 4 else year - 1


def prev_month_key(key: str) -> str:
    y, m = int(key[:4]), int(key[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def fy_month_keys(fy: int) -> list[tuple[str, int]]:
    """[(YYYY-MM, calendar month)] for the 12 months of a financial year, April first."""
    return [(f"{fy if m >= 4 else fy + 1}-{m:02d}", m) for m in FY_MONTHS]


def build_frame(payload: dict) -> pd.DataFrame:
    rows = payload.get("rows") or []
    df = pd.DataFrame(rows, columns=["month", "office_code", "maker", "fuel", "regs"])
    offices = pd.DataFrame(payload.get("offices") or [], columns=["code", "office", "town", "hub"])
    df = df.merge(offices.rename(columns={"code": "office_code"}), on="office_code", how="left")
    df["regs"] = pd.to_numeric(df["regs"], errors="coerce").fillna(0).astype(int)
    df["year"] = df["month"].str[:4].astype(int)
    df["cal_month"] = df["month"].str[5:7].astype(int)
    df["fy"] = [fy_of(y, m) for y, m in zip(df["year"], df["cal_month"])]
    return df


@dataclass
class Filters:
    hubs: list[str] = field(default_factory=list)
    towns: list[str] = field(default_factory=list)
    rtos: list[str] = field(default_factory=list)
    fys: list[int] = field(default_factory=list)
    months: list[int] = field(default_factory=list)
    fuels: list[str] = field(default_factory=list)


@dataclass
class Progress:
    month: str          # month in progress, YYYY-MM
    elapsed: int | None
    days: int | None

    @property
    def factor(self) -> float:
        if self.elapsed and self.days and self.elapsed < self.days:
            return self.days / self.elapsed
        return 1.0


def progress_from(status: dict, df: pd.DataFrame) -> Progress:
    dd = (status or {}).get("data_date")
    if dd:
        y, m, d = int(dd[:4]), int(dd[5:7]), int(dd[8:10])
        return Progress(f"{y}-{m:02d}", d, calendar.monthrange(y, m)[1])
    return Progress(df["month"].max() if len(df) else "", None, None)


class Dash:
    """All figures for one set of filters."""

    def __init__(self, df: pd.DataFrame, f: Filters, prog: Progress):
        self.df, self.f, self.prog = df, f, prog
        self.all_fys = sorted(df["fy"].unique().tolist()) if len(df) else []
        self.fys = sorted(f.fys) if f.fys else self.all_fys
        self.single = len(self.fys) == 1
        self.latest = df["month"].max() if len(df) else ""
        self.ly_loaded = self.single and bool((df["fy"] == self.fys[0] - 1).any())
        # selected month keys, up to the latest loaded month
        self.sel = sorted(
            (k, m) for fy in self.fys for k, m in fy_month_keys(fy)
            if (not f.months or m in f.months) and k <= self.latest
        )
        self.sel_cal = {m for _, m in self.sel}
        self.pm_in = any(k == prog.month for k, _ in self.sel)
        # growth over last month: latest selected month vs the month before it
        self.focus = self.sel[-1][0] if self.sel else None
        self.prev = prev_month_key(self.focus) if self.focus else None
        self.focus_in_progress = self.focus is not None and self.focus == prog.month
        self.prev_loaded = self.prev is not None and bool((df["month"] == self.prev).any())

    # --- slicing -------------------------------------------------------
    def _slice(self, geo=True, rto=True, fuel=True, months=True) -> pd.DataFrame:
        d, f = self.df, self.f
        mask = pd.Series(True, index=d.index)
        if geo and f.hubs:
            mask &= d["hub"].isin(f.hubs)
        if geo and f.towns:
            mask &= d["town"].isin(f.towns)
        if rto and f.rtos:
            mask &= d["office_code"].isin(f.rtos)
        if fuel and f.fuels:
            mask &= d["fuel"].isin(f.fuels)
        if months and f.months:
            mask &= d["cal_month"].isin(f.months)
        return d[mask]

    def _compare(self, d: pd.DataFrame, by: str | None, dm: pd.DataFrame | None = None) -> pd.DataFrame:
        """regs, regs_pm, regs_pr, regs_ly, share, change, change_pr, plus month-on-month
        (regs_fm, regs_prev, mom, mom_pr) grouped by `by` (or one row).
        `dm` is the same slice without the month filter, for the previous month."""
        key = by or "_all"
        d = d.assign(_all="All") if by is None else d
        if dm is None:
            dm = d
        elif by is None:
            dm = dm.assign(_all="All")
        cur = d[d["fy"].isin(self.fys)]
        out = cur.groupby(key)["regs"].sum().rename("regs").to_frame()
        out["regs_pm"] = cur[cur["month"] == self.prog.month].groupby(key)["regs"].sum()
        if self.single:
            ly = d[(d["fy"] == self.fys[0] - 1) & d["cal_month"].isin(self.sel_cal)]
            out = out.join(ly.groupby(key)["regs"].sum().rename("regs_ly"), how="outer")
        else:
            out["regs_ly"] = pd.NA
        out = out.fillna({"regs": 0, "regs_pm": 0})
        out["regs_pr"] = (out["regs"] + out["regs_pm"] * (self.prog.factor - 1)).round().astype(int)
        total = out["regs"].sum()
        out["share"] = out["regs"] / total if total else pd.NA
        if self.ly_loaded:
            ly_ = pd.to_numeric(out["regs_ly"], errors="coerce").fillna(0)
            out["regs_ly"] = ly_.astype(int)
            out["change"] = (out["regs"] / ly_.where(ly_ > 0)) - 1
            out["change_pr"] = (out["regs_pr"] / ly_.where(ly_ > 0)) - 1
        else:
            out["regs_ly"] = pd.NA
            out["change"] = pd.NA
            out["change_pr"] = pd.NA
        # month on month
        if self.focus and self.prev_loaded:
            fm = dm[dm["month"] == self.focus].groupby(key)["regs"].sum()
            pv = dm[dm["month"] == self.prev].groupby(key)["regs"].sum()
            out["regs_fm"] = fm.reindex(out.index).fillna(0).astype(int)
            out["regs_prev"] = pv.reindex(out.index).fillna(0).astype(int)
            base = out["regs_prev"].where(out["regs_prev"] > 0)
            f = self.prog.factor if self.focus_in_progress else 1.0
            out["mom"] = out["regs_fm"] / base - 1
            out["mom_pr"] = (out["regs_fm"] * f) / base - 1
        else:
            out["regs_fm"] = pd.NA
            out["regs_prev"] = pd.NA
            out["mom"] = pd.NA
            out["mom_pr"] = pd.NA
        out = out[(out["regs"] > 0) | (pd.to_numeric(out["regs_ly"], errors="coerce").fillna(0) > 0)]
        out["regs"] = out["regs"].astype(int)
        return out.sort_values("regs", ascending=False)

    # --- figures -------------------------------------------------------
    def kpi(self) -> dict:
        t = self._compare(self._slice(), None, self._slice(months=False))
        row = t.iloc[0].to_dict() if len(t) else {"regs": 0, "regs_pr": 0, "regs_ly": pd.NA, "change": pd.NA, "change_pr": pd.NA, "regs_pm": 0,
                                                  "regs_fm": pd.NA, "regs_prev": pd.NA, "mom": pd.NA, "mom_pr": pd.NA}
        d = self._slice()
        pm_mtd = int(d[(d["month"] == self.prog.month) & d["fy"].isin(self.fys)]["regs"].sum()) if self.pm_in else None
        ly_key = f"{int(self.prog.month[:4]) - 1}{self.prog.month[4:]}" if self.prog.month else ""
        pm_ly = int(d[d["month"] == ly_key]["regs"].sum()) if self.pm_in and (self.df["month"] == ly_key).any() else None
        pm_pr = round(pm_mtd * self.prog.factor) if pm_mtd is not None else None
        nan = lambda v: None if v is pd.NA or (isinstance(v, float) and pd.isna(v)) else v
        return {
            "regs": int(row["regs"]), "regs_pr": int(row["regs_pr"]),
            "regs_ly": nan(row.get("regs_ly")), "change": nan(row.get("change")), "change_pr": nan(row.get("change_pr")),
            "no_cmp": "" if nan(row.get("change")) is not None else ("multi" if not self.single else "ly"),
            "first": self.sel[0][0] if self.sel else None, "last": self.sel[-1][0] if self.sel else None,
            "n_months": len(self.sel), "pm_in": self.pm_in,
            "pm_mtd": pm_mtd, "pm_pr": pm_pr, "pm_ly": pm_ly,
            "pm_change": (pm_mtd / pm_ly - 1) if pm_mtd is not None and pm_ly else None,
            "pm_change_pr": (pm_pr / pm_ly - 1) if pm_pr is not None and pm_ly else None,
            "focus": self.focus, "prev": self.prev, "focus_in_progress": self.focus_in_progress,
            "fm": nan(row.get("regs_fm")),
            "fm_pr": round(nan(row.get("regs_fm")) * self.prog.factor) if self.focus_in_progress and nan(row.get("regs_fm")) is not None else nan(row.get("regs_fm")),
            "prev_v": nan(row.get("regs_prev")),
            "mom": nan(row.get("mom")), "mom_pr": nan(row.get("mom_pr")),
        }

    def trend(self) -> pd.DataFrame:
        """Latest selected FY by month (ignores the month filter), with the year before and pro-rata."""
        fy = max(self.fys) if self.fys else 0
        d = self._slice(months=False)
        by_month = d.groupby("month")["regs"].sum()
        loaded = set(self.df["month"].unique())
        out = []
        for key, m in fy_month_keys(fy):
            ly_key = f"{int(key[:4]) - 1}{key[4:]}"
            cur = int(by_month.get(key, 0)) if key <= self.latest else None
            prog = key == self.prog.month
            out.append({
                "month": key, "label": MONTH_NAMES[m], "cal_month": m, "fy": fy,
                "regs": cur, "regs_pr": round(cur * self.prog.factor) if prog and cur is not None else None,
                "regs_ly": int(by_month.get(ly_key, 0)) if ly_key in loaded else None,
                "in_progress": prog, "picked": (not self.f.months) or m in self.f.months,
            })
        return pd.DataFrame(out)

    def by_hub(self) -> pd.DataFrame:
        return self._compare(self._slice(geo=False, rto=False), "hub", self._slice(geo=False, rto=False, months=False)).reset_index()

    def by_rto(self) -> pd.DataFrame:
        t = self._compare(self._slice(rto=False), "office_code", self._slice(rto=False, months=False))
        info = self.df.drop_duplicates("office_code").set_index("office_code")[["office", "town", "hub"]]
        return t.join(info).reset_index()

    def by_fuel(self) -> pd.DataFrame:
        return self._compare(self._slice(fuel=False), "fuel", self._slice(fuel=False, months=False)).reset_index()

    def makers(self) -> pd.DataFrame:
        t = self._compare(self._slice(), "maker", self._slice(months=False)).reset_index()
        t.insert(0, "rank", range(1, len(t) + 1))
        return t
