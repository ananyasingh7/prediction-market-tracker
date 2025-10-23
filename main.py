import time
import requests
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from web3 import Web3
from rich.console import Console
from rich.table import Table
from rich.live import Live
import typer

# Config
POLYGON_RPC = "https://polygon-rpc.com"
SUBGRAPH_URL = "https://api.thegraph.com/subgraphs/name/polymarket/ctf-mainnet"
WHALE_THRESHOLD_USD = 50000

w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
console = Console()
app = typer.Typer()

# The Graph query for recent large trades
QUERY = gql("""
query GetWhaleTrades($timestamp: BigInt!) {
  trades(
    first: 100
    orderBy: timestamp
    orderDirection: desc
    where: {timestamp_gt: $timestamp}
  ) {
    id
    type
    amount
    timestamp
    account
    market {
      id
      question
    }
  }
}
""")

def fetch_whale_trades(market_id: str, since_ts: int):
    transport = RequestsHTTPTransport(url=SUBGRAPH_URL)
    client = Client(transport=transport, fetch_schema_from_transport=False)
    
    params = {"timestamp": since_ts}
    result = client.execute(QUERY, variable_values=params)
    
    whales = []
    for trade in result['trades']:
        amount = float(trade['amount'])
        if amount >= WHALE_THRESHOLD_USD:
            whales.append({
                'wallet': trade['account'],
                'amount_usd': amount,
                'market': trade['market']['question'][:50] + '...',
                'timestamp': trade['timestamp']
            })
    return sorted(whales, key=lambda x: x['amount_usd'], reverse=True)[:10]

@app.command()
def track_whales(market_filter: str = "all", since: int = int((time.time() - 3600) * 1000)):  # Last hour
    """Track whales in real-time (CLI dashboard)."""
    def update_display():
        trades = fetch_whale_trades(market_filter, since)
        table = Table(title="Polymarket Whale Tracker")
        table.add_column("Wallet", style="cyan")
        table.add_column("Amount (USD)", justify="right")
        table.add_column("Market", style="magenta")
        table.add_column("Time (Unix)", justify="right")
        
        for t in trades:
            table.add_row(t['wallet'][:10] + '...', f"${t['amount_usd']:,.0f}", t['market'], str(t['timestamp']))
            
            # Alert on new big trade
            if t['amount_usd'] > 100000:
                alert = f"🐋 New Whale: ${t['amount_usd']:,.0f} on {t['market']}"
                console.print(f"[red]{alert}[/red]")
        
        return table
    
    with Live(update_display(), refresh_per_second=5, screen=True) as live:  # Live updates
        try:
            while True:
                time.sleep(1)  # Poll loop
        except KeyboardInterrupt:
            console.print("Tracking stopped.")

if __name__ == "__main__":
    app()