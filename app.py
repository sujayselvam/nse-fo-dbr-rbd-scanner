
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta

st.set_page_config(
    page_title="NSE F&O DBR / RBD Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("NSE F&O – DBR / RBD Supply & Demand Scanner")
st.caption("Daily candles | Strict experimental pattern detection | Historical fresh zones")

UNIVERSE_FILE = Path("fo_universe.csv")


@st.cache_data(ttl=3600)
def load_universe():
    if not UNIVERSE_FILE.exists():
        return []

    df = pd.read_csv(UNIVERSE_FILE)
    col = "symbol" if "symbol" in df.columns else df.columns[0]

    symbols = df[col].dropna().astype(str).str.strip().str.upper()
    symbols = [
        s if s.endswith(".NS") else s + ".NS"
        for s in symbols if s and s.lower() != "nan"
    ]
    return sorted(set(symbols))


def get_history(symbol):
    try:
        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False
        )

        if df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close"]
        if not all(c in df.columns for c in required):
            return None

        df = df[required].dropna().copy()
        return df

    except Exception:
        return None


def detect_zones(df, symbol, lookback_days=180):
    results = []

    if df is None or len(df) < 30:
        return results

    df = df.copy()

    df["ATR"] = (
        pd.concat([
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs()
        ], axis=1).max(axis=1).rolling(14).mean()
    )

    df = df.dropna(subset=["ATR"])
    if len(df) < 10:
        return results

    cutoff = df.index[-1] - pd.Timedelta(days=lookback_days)

    for i in range(4, len(df) - 1):

        atr = float(df["ATR"].iloc[i])
        if not np.isfinite(atr) or atr <= 0:
            continue

        for base_len in (1, 2, 3):

            start = i
            end = i + base_len - 1
            departure = end + 1

            if departure >= len(df):
                continue

            base = df.iloc[start:end + 1]
            before = df.iloc[i - 3:i]
            move = df.iloc[departure]

            base_high = float(base["High"].max())
            base_low = float(base["Low"].min())
            base_range = base_high - base_low

            # Compact base requirement
            if base_range > 1.5 * atr:
                continue

            if (base["High"] - base["Low"] > 0.7 * atr).any():
                continue

            # Prior directional impulse
            prior_change = (
                float(df["Close"].iloc[i - 1])
                - float(df["Close"].iloc[i - 3])
            )

            body = abs(float(move["Close"]) - float(move["Open"]))

            # DBR: Drop, Base, Rally
            if (
                prior_change <= -1.0 * atr
                and move["Close"] > move["Open"]
                and body >= 0.8 * atr
                and move["Close"] > base_high
            ):
                pattern = "DBR"
                proximal = float(
                    base[["Open", "Close"]].max(axis=1).max()
                )
                distal = base_low

            # RBD: Rally, Base, Drop
            elif (
                prior_change >= 1.0 * atr
                and move["Close"] < move["Open"]
                and body >= 0.8 * atr
                and move["Close"] < base_low
            ):
                pattern = "RBD"
                proximal = float(
                    base[["Open", "Close"]].min(axis=1).min()
                )
                distal = base_high

            else:
                continue

            formation_date = df.index[departure]

            if formation_date < cutoff:
                continue

            # Check every candle after departure
            future = df.iloc[departure + 1:]

            status = "Fresh"

            if pattern == "DBR":
                for _, candle in future.iterrows():
                    if candle["Low"] < distal:
                        status = "Invalidated"
                        break
                    if candle["Low"] <= proximal:
                        status = "Tested"

            else:
                for _, candle in future.iterrows():
                    if candle["High"] > distal:
                        status = "Invalidated"
                        break
                    if candle["High"] >= proximal:
                        status = "Tested"

            latest_close = float(df["Close"].iloc[-1])
            age = (df.index[-1] - formation_date).days

            results.append({
                "Symbol": symbol.replace(".NS", ""),
                "Pattern": pattern,
                "Formation Date": formation_date.strftime("%Y-%m-%d"),
                "Proximal": round(proximal, 2),
                "Distal": round(distal, 2),
                "Latest Close": round(latest_close, 2),
                "Status": status,
                "Age (days)": age
            })

            # Avoid duplicate base lengths at the same departure
            break

    return results


# Dashboard controls
symbols = load_universe()

st.sidebar.header("Scanner Settings")

lookback = st.sidebar.selectbox(
    "Historical window",
    [90, 180, 270, 365],
    index=1
)

st.sidebar.write(f"Stocks in universe: {len(symbols)}")

if not symbols:
    st.error("No stock symbols found in fo_universe.csv")

if st.button("🔍 Run Scan Now", type="primary"):
    if not symbols:
        st.error("Please check fo_universe.csv")
    else:
        all_results = []
        progress = st.progress(0)
        message = st.empty()

        for number, symbol in enumerate(symbols):
            message.write(f"Scanning {symbol} ({number + 1}/{len(symbols)})")

            history = get_history(symbol)

            if history is not None:
                all_results.extend(
                    detect_zones(history, symbol, lookback)
                )

            progress.progress((number + 1) / len(symbols))

        st.session_state["scan_results"] = pd.DataFrame(all_results)
        st.session_state["scan_time"] = datetime.now().strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        message.success("Scan completed!")

if "scan_results" in st.session_state:

    results = st.session_state["scan_results"]

    st.caption(
        "Last scan: " + st.session_state.get("scan_time", "Unknown")
    )

    if results.empty:
        st.warning("No qualifying patterns detected.")
    else:
        latest_dbr = results[results["Pattern"] == "DBR"]
        latest_rbd = results[results["Pattern"] == "RBD"]

        fresh = results[results["Status"] == "Fresh"]

        col1, col2, col3 = st.columns(3)
        col1.metric("DBR formations", len(latest_dbr))
        col2.metric("RBD formations", len(latest_rbd))
        col3.metric("Historical fresh zones", len(fresh))

        tab1, tab2, tab3, tab4 = st.tabs([
            "Latest DBR",
            "Latest RBD",
            "Historical Fresh Zones",
            "All Results"
        ])

        with tab1:
            st.dataframe(
                latest_dbr.sort_values(
                    "Formation Date", ascending=False
                ),
                use_container_width=True,
                hide_index=True
            )

        with tab2:
            st.dataframe(
                latest_rbd.sort_values(
                    "Formation Date", ascending=False
                ),
                use_container_width=True,
                hide_index=True
            )

        with tab3:
            st.dataframe(
                fresh.sort_values(
                    "Formation Date", ascending=False
                ),
                use_container_width=True,
                hide_index=True
            )

        with tab4:
            st.dataframe(
                results.sort_values(
                    "Formation Date", ascending=False
                ),
                use_container_width=True,
                hide_index=True
            )

        csv = results.to_csv(index=False).encode("utf-8")

        st.download_button(
            "⬇ Download Scan Results CSV",
            data=csv,
            file_name="NSE_DBR_RBD_Scan.csv",
            mime="text/csv"
        )

st.divider()

st.caption(
    "Data source: Yahoo Finance (unofficial). "
    "Experimental pattern rules; verify all signals against actual charts. "
    "This version does not perform automatic daily scans."
)
