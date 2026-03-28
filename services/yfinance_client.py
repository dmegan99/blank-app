"""yfinance wrapper for stock data."""

import yfinance as yf
import numpy as np
import pandas as pd


def get_stock_info(ticker: str) -> dict:
    """Get comprehensive stock info from yfinance."""
    stock = yf.Ticker(ticker)
    try:
        info = stock.info
        if not info or info.get("trailingPegRatio") is None and len(info) < 5:
            # Possibly empty/failed — try fast_info as fallback
            fi = stock.fast_info
            info = dict(info) if info else {}
            info.setdefault("regularMarketPrice", getattr(fi, "last_price", None))
            info.setdefault("marketCap", getattr(fi, "market_cap", None))
            info.setdefault("fiftyTwoWeekHigh", getattr(fi, "year_high", None))
            info.setdefault("fiftyTwoWeekLow", getattr(fi, "year_low", None))
    except Exception:
        # Last resort: try fast_info only
        try:
            fi = stock.fast_info
            info = {
                "regularMarketPrice": getattr(fi, "last_price", None),
                "marketCap": getattr(fi, "market_cap", None),
                "fiftyTwoWeekHigh": getattr(fi, "year_high", None),
                "fiftyTwoWeekLow": getattr(fi, "year_low", None),
            }
        except Exception:
            info = {}
    return info


def get_news(ticker: str, max_items: int = 10) -> list[dict]:
    """Get recent news headlines for a ticker from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if not news:
            return []
        results = []
        for item in news[:max_items]:
            content = item.get("content", {})
            results.append({
                "title": content.get("title", ""),
                "publisher": content.get("provider", {}).get("displayName", ""),
                "link": content.get("canonicalUrl", {}).get("url", ""),
                "published": content.get("pubDate", ""),
            })
        return results
    except Exception:
        return []


def get_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Get historical price data."""
    stock = yf.Ticker(ticker)
    return stock.history(period=period, interval=interval)


def calculate_rsi(prices: pd.Series, period: int = 14) -> float | None:
    """Calculate RSI (Relative Strength Index)."""
    if len(prices) < period + 1:
        return None

    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    last_avg_gain = avg_gain.iloc[-1]
    last_avg_loss = avg_loss.iloc[-1]

    if last_avg_loss == 0:
        return 100.0

    rs = last_avg_gain / last_avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(prices: pd.Series) -> dict | None:
    """Calculate MACD (12, 26, 9)."""
    if len(prices) < 35:
        return None

    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "macd": macd_line.iloc[-1],
        "signal": signal_line.iloc[-1],
        "histogram": histogram.iloc[-1],
        "crossover": (
            "bullish" if (histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0)
            else "bearish" if (histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0)
            else "none"
        ),
    }


def calculate_fibonacci(high: float, low: float) -> dict:
    """Calculate Fibonacci retracement levels from high/low."""
    diff = high - low
    return {
        "0.0%": high,
        "23.6%": high - diff * 0.236,
        "38.2%": high - diff * 0.382,
        "50.0%": high - diff * 0.5,
        "61.8%": high - diff * 0.618,
        "78.6%": high - diff * 0.786,
        "100.0%": low,
    }


def screen_ticker(ticker: str) -> dict | None:
    """Run technical screening on a single ticker."""
    try:
        hist = get_price_history(ticker, period="1y")
        if hist.empty or len(hist) < 35:
            return None

        close = hist["Close"]
        current_price = close.iloc[-1]
        high_52w = close.max()
        low_52w = close.min()

        rsi = calculate_rsi(close)
        macd = calculate_macd(close)
        fib = calculate_fibonacci(high_52w, low_52w)

        # Determine signals
        signals = []
        if rsi is not None:
            if rsi < 30:
                signals.append("RSI oversold")
            elif rsi > 70:
                signals.append("RSI overbought")

        if macd and macd["crossover"] == "bullish":
            signals.append("MACD bullish cross")
        elif macd and macd["crossover"] == "bearish":
            signals.append("MACD bearish cross")

        # Check proximity to Fibonacci levels (within 2%)
        for level_name, level_price in fib.items():
            if level_name in ("0.0%", "100.0%"):
                continue
            pct_diff = abs(current_price - level_price) / level_price * 100
            if pct_diff < 2:
                signals.append(f"Near Fib {level_name}")

        # SMA 50 & 200
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

        # Average volume comparison (recent 5d vs 20d)
        vol = hist["Volume"] if "Volume" in hist.columns else None
        vol_ratio = None
        if vol is not None and len(vol) >= 20:
            avg5 = float(vol.iloc[-5:].mean())
            avg20 = float(vol.iloc[-20:].mean())
            if avg20 > 0:
                vol_ratio = avg5 / avg20

        if sma50 and sma200:
            if sma50 > sma200 and close.iloc[-2] <= sma200:
                signals.append("Golden cross area")
            elif sma50 < sma200 and close.iloc[-2] >= sma200:
                signals.append("Death cross area")

        if vol_ratio and vol_ratio > 2.0:
            signals.append("Volume spike")

        # Nearest Fibonacci level
        nearest_fib = None
        nearest_fib_dist = 999
        for level_name, level_price in fib.items():
            if level_name in ("0.0%", "100.0%"):
                continue
            pct_diff = (current_price - level_price) / level_price * 100
            if abs(pct_diff) < abs(nearest_fib_dist):
                nearest_fib_dist = pct_diff
                nearest_fib = level_name

        return {
            "ticker": ticker,
            "price": current_price,
            "rsi": rsi,
            "macd_hist": macd["histogram"] if macd else None,
            "macd_cross": macd["crossover"] if macd else None,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pct_from_high": ((current_price - high_52w) / high_52w) * 100,
            "sma50": sma50,
            "sma200": sma200,
            "vol_ratio": vol_ratio,
            "nearest_fib": nearest_fib,
            "nearest_fib_dist": nearest_fib_dist,
            "signals": signals,
        }
    except Exception:
        return None
