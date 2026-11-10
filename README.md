# NSE F&O DBR/RBD Scanner — Cloud starter

## Important status
This is a deployable **starter**, not yet a verified full-market production scanner.
The included `fo_universe.csv` contains only 10 example symbols. Replace it with the complete current NSE F&O underlying list before treating results as market-wide.
Daily candles are fetched from Yahoo Finance via `yfinance`, an unofficial free source. Availability, history, adjustments and terms can change. This is not an NSE-authorised data feed.

## Deploy on Streamlit Community Cloud
1. Create/sign in to GitHub.
2. Create a new repository and upload all files in this folder.
3. Go to https://share.streamlit.io/ and connect GitHub.
4. Choose your repository, branch `main`, and `app.py`.
5. Deploy. Your dashboard URL will be provided by Streamlit.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Update the F&O universe
Edit `fo_universe.csv`: one NSE equity symbol per row, without `.NS`.
Do not include index symbols or option contracts; include underlying stock symbols only.

## Current scanner rules
- 1–3 compact base candles
- Each base candle range <= 0.7 x ATR(14)
- Total base height <= 1.5 x ATR(14)
- Prior impulse body >= 0.8 x ATR(14)
- Departure body >= 0.8 x ATR(14)
- DBR: bearish impulse, bullish departure closing above base high
- RBD: bullish impulse, bearish departure closing below base low
- Zone freshness checked against later daily candle overlap
- Historical window: 180 calendar days

These are initial explicit rules and should be reviewed/validated before live trading use.
