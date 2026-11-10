import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone
from pathlib import Path

st.set_page_config(page_title="NSE F&O DBR / RBD Scanner", page_icon="📊", layout="wide")
st.title("NSE F&O — DBR / RBD Supply & Demand Scanner")
st.caption("Daily timeframe • 180-calendar-day fresh-zone search • Free-data prototype")

UNIVERSE_FILE = Path("fo_universe.csv")

@st.cache_data(ttl=3600, show_spinner=False)
def load_universe():
    if not UNIVERSE_FILE.exists():
        return []
    df = pd.read_csv(UNIVERSE_FILE)
    col = "symbol" if "symbol" in df.columns else df.columns[0]
    vals = df[col].dropna().astype(str).str.strip().str.upper().tolist()
    return sorted(set(v if v.endswith(".NS") else v + ".NS" for v in vals if v and v.lower() != "nan"))

def download_history(symbols, period="1y"):
    # Yahoo Finance is an unofficial free source, not an NSE-authorised feed.
    raw = yf.download(
        tickers=symbols, period=period, interval="1d",
        group_by="ticker", auto_adjust=False, progress=False,
        threads=True, timeout=25
    )
    out = {}
    if raw is None or raw.empty:
        return out
    if isinstance(raw.columns, pd.MultiIndex):
        for sym in symbols:
            if sym in raw.columns.get_level_values(0):
                d = raw[sym].copy()
                d = d.dropna(subset=["Open","High","Low","Close"])
                if not d.empty: out[sym] = d
    else:
        sym = symbols[0]
        d = raw.dropna(subset=["Open","High","Low","Close"])
        if not d.empty: out[sym] = d
    return out

def atr_series(df, n=14):
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()

def detect_zones(symbol, df, days=180, max_base=3):
    d = df.copy().dropna(subset=["Open","High","Low","Close"])
    d["ATR"] = atr_series(d)
    if len(d) < 25: return []
    cutoff = pd.Timestamp.now(tz=None).normalize() - pd.Timedelta(days=days)
    rows = []
    # Pattern: one strong impulse into base, 1..3 compact base candles,
    # then one strong departure candle breaking the base.
    for base_n in range(1, max_base + 1):
        for dep_i in range(15, len(d)):
            base_end = dep_i - 1
            base_start = base_end - base_n + 1
            impulse_i = base_start - 1
            if impulse_i < 14: continue
            imp = d.iloc[impulse_i]
            dep = d.iloc[dep_i]
            base = d.iloc[base_start:base_end+1]
            atr = d.iloc[dep_i]["ATR"]
            if pd.isna(atr) or atr <= 0: continue
            base_height = float(base["High"].max() - base["Low"].min())
            compact = ((base["High"] - base["Low"]) <= 0.7 * atr).all() and base_height <= 1.5 * atr
            if not compact: continue
            imp_body = abs(float(imp["Close"] - imp["Open"]))
            dep_body = abs(float(dep["Close"] - dep["Open"]))
            if imp_body < 0.8 * float(d.iloc[impulse_i]["ATR"] if not pd.isna(d.iloc[impulse_i]["ATR"]) else atr): continue
            if dep_body < 0.8 * atr: continue

            # Drop-Base-Rally: bearish impulse, bullish departure, close above base high.
            # Rally-Base-Drop: bullish impulse, bearish departure, close below base low.
            pattern = None
            proximal = distal = None
            if imp["Close"] < imp["Open"] and dep["Close"] > dep["Open"] and dep["Close"] > base["High"].max():
                pattern = "DBR"
                proximal = float(np.maximum(base["Open"], base["Close"]).max())
                distal = float(base["Low"].min())
            elif imp["Close"] > imp["Open"] and dep["Close"] < dep["Open"] and dep["Close"] < base["Low"].min():
                pattern = "RBD"
                proximal = float(np.minimum(base["Open"], base["Close"]).min())
                distal = float(base["High"].max())
            if not pattern: continue

            formation_date = pd.Timestamp(d.index[dep_i]).tz_localize(None) if getattr(d.index[dep_i], "tzinfo", None) else pd.Timestamp(d.index[dep_i])
            if formation_date < cutoff: continue
            # A later candle has mitigated the zone if its range intersects the zone.
            later = d.iloc[dep_i+1:]
            if pattern == "DBR":
                touched = bool(((later["Low"] <= proximal) & (later["High"] >= distal)).any())
                invalid = bool((later["Close"] < distal).any())
            else:
                touched = bool(((later["High"] >= proximal) & (later["Low"] <= distal)).any())
                invalid = bool((later["Close"] > distal).any())
            status = "Invalidated" if invalid else ("Touched" if touched else "Fresh")
            rows.append({
                "Symbol": symbol.replace(".NS",""),
                "Pattern": pattern,
                "Formation date": formation_date.date().isoformat(),
                "Proximal": round(proximal, 2),
                "Distal": round(distal, 2),
                "Latest close": round(float(d["Close"].iloc[-1]), 2),
                "Status": status,
                "Age (calendar days)": (pd.Timestamp.now().normalize() - formation_date.normalize()).days
            })
    # Deduplicate identical pattern/date/zone rows
    unique = {}
    for r in rows:
        k = (r["Symbol"], r["Pattern"], r["Formation date"], r["Proximal"], r["Distal"])
        unique[k] = r
    return list(unique.values())

st.info("Data source: Yahoo Finance daily candles (free, unofficial). Verify prices against Dhan/NSE before trading. This is a research scanner, not investment advice.")
symbols = load_universe()
if not symbols:
    st.error("No symbols found. Add NSE symbols (one per row) to fo_universe.csv, without .NS suffix.")
    st.stop()

with st.sidebar:
    st.header("Scanner settings")
    days = st.selectbox("Historical fresh-zone window", [180], index=0)
    base_n = st.selectbox("Maximum base candles", [1,2,3], index=2)
    st.caption(f"Universe file: {len(symbols)} symbols")
    run = st.button("Run scan now", type="primary", use_container_width=True)

if run or "scan_results" not in st.session_state:
    with st.spinner(f"Downloading daily candles and scanning {len(symbols)} symbols..."):
        frames = download_history(symbols, period="1y")
        found = []
        errors = []
        for sym in symbols:
            df = frames.get(sym)
            if df is None or df.empty:
                errors.append(sym)
                continue
            found.extend(detect_zones(sym, df, days=days, max_base=base_n))
        st.session_state["scan_results"] = pd.DataFrame(found)
        st.session_state["scan_errors"] = errors
        st.session_state["scan_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

results = st.session_state["scan_results"]
errors = st.session_state["scan_errors"]
st.caption(f"Last scan: {st.session_state['scan_time']} • Symbols with data: {len(symbols)-len(errors)}/{len(symbols)}")
if errors:
    with st.expander(f"Symbols with missing data ({len(errors)})"):
        st.write(", ".join(s.replace(".NS","") for s in errors))

if results.empty:
    st.warning("No patterns detected in the downloaded data. This can be a valid result; it does not mean the scanner is broken.")
else:
    latest_dbr = results[results["Pattern"]=="DBR"].sort_values("Formation date", ascending=False)
    latest_rbd = results[results["Pattern"]=="RBD"].sort_values("Formation date", ascending=False)
    fresh = results[results["Status"]=="Fresh"].sort_values("Formation date", ascending=False)
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("DBR formations", len(latest_dbr))
    c2.metric("RBD formations", len(latest_rbd))
    c3.metric("Fresh zones", len(fresh))
    c4.metric("Invalidated / touched", len(results)-len(fresh))
    tabs = st.tabs(["Latest DBR","Latest RBD","Historical fresh zones","All detected zones"])
    with tabs[0]: st.dataframe(latest_dbr, use_container_width=True, hide_index=True)
    with tabs[1]: st.dataframe(latest_rbd, use_container_width=True, hide_index=True)
    with tabs[2]: st.dataframe(fresh, use_container_width=True, hide_index=True)
    with tabs[3]: st.dataframe(results.sort_values("Formation date", ascending=False), use_container_width=True, hide_index=True)
    st.download_button("Download scan results CSV", results.to_csv(index=False), "dbr_rbd_scan.csv", "text/csv")

st.caption("Pattern rules are explicit but still need validation against your preferred strict supply/demand interpretation. Corporate-action adjustments and data-provider gaps can affect zones.")
