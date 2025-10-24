import time
import requests
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from datetime import datetime, timezone

API_URL = "https://data-api.polymarket.com/trades"
THRESHOLD_USD = 7500  # adjust threshold
POLL_INTERVAL = 10    # seconds

console = Console()

def fetch_trades(limit=50):
    resp = requests.get(API_URL, params={"limit": limit})
    resp.raise_for_status()
    return resp.json()

def format_time(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def print_trade(t):
    usd_value = float(t["price"]) * float(t["size"])
    side = t["side"].upper()
    color = "green" if side == "BUY" else "red"
    title = Text(f"🐋  {t['title']}", style="bold cyan")

    body = (
        f"[bold]{side}[/bold]  |  [white]${usd_value:,.0f}[/white]\n"
        f"[dim]────────────────────────────[/dim]\n"
        f"[bold]Price:[/bold] {float(t['price']):.3f}\n"
        f"[bold]Size:[/bold]  {float(t['size']):,.2f}\n"
        f"[bold]Outcome:[/bold] {t.get('outcome', '?')}\n"
        f"[bold]Maker:[/bold] [dim]{t.get('maker', '?')[:10]}…[/dim]\n"
        f"[bold]Taker:[/bold] [dim]{t.get('taker', '?')[:10]}…[/dim]\n"
        f"[bold]Tx:[/bold] [dim]{t['transactionHash'][:16]}…[/dim]\n"
        f"[bold]Time:[/bold] {format_time(int(t['timestamp']))}"
    )

    console.print(Panel(body, title=title, border_style=color, expand=False))

def main():
    seen = set()
    console.print("[bold blue]🔍 Polymarket Whale Tracker running...[/bold blue]\n")

    while True:
        trades = fetch_trades(100)
        for t in trades:
            tx = t["transactionHash"]
            if tx in seen:
                continue
            seen.add(tx)

            usd_value = float(t["price"]) * float(t["size"])
            if usd_value >= THRESHOLD_USD:
                print_trade(t)

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()