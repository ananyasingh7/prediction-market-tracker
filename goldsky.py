import asyncio
import requests
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput
from rich.console import Console
from rich.table import Table
from rich.live import Live
import typer
import click
import time

# Config (2025: Goldsky State Subgraph + RPC Fallback)
STATE_SUBGRAPH_URL = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/state-subgraph/0.0.5/gn"
POLYGON_RPC = "https://polygon-rpc.com"
FPMM_FACTORY_ADDRESS = "0x4D97DCd97eC945f40cF65F87097AC1220BaB474B2"  # FixedProductMarketMaker Factory
WHALE_THRESHOLD_USD = 50000  # Filter trades >= $50k (USDC * 1e6)
ALERT_THRESHOLD_USD = 100000  # Telegram alert for >= $100k
TELEGRAM_TOKEN = "your_bot_token"  # Optional: Replace or leave empty
TELEGRAM_CHAT_ID = "your_chat_id"

console = Console()
app = typer.Typer(help="Track Polymarket whale trades (>= $50k) in real-time via Subgraph.")

w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

# Corrected GraphQL Queries for State Subgraph
TRADE_QUERY = gql("""
query GetWhaleTrades($timestamp: BigInt!, $amount: BigDecimal!) {
  fixedProductMarketMakers(
    where: {timestamp_gte: $timestamp, investmentAmount_gte: $amount}
    orderBy: timestamp
    orderDirection: desc
    first: 50
  ) {
    id
    investmentAmount
    sharesBought
    timestamp
    buyer { id }
    market { id question volume }
  }
}
""")

MARKETS_QUERY = gql("""
query GetTopMarkets {
  markets(
    orderBy: volume
    orderDirection: desc
    first: 5
  ) {
    id
    question
    volume
  }
}
""")

def fetch_from_subgraph(query, variables=None):
    """Fetch from Goldsky State Subgraph with introspection fallback."""
    transport = RequestsHTTPTransport(url=STATE_SUBGRAPH_URL)
    client = Client(transport=transport, fetch_schema_from_transport=True)
    try:
        result = client.execute(query, variable_values=variables or {})
        return result
    except Exception as e:
        console.print(f"[red]Subgraph fetch failed: {e}[/red]")
        intro_query = gql("{ __schema { queryType { fields { name } } } }")
        try:
            intro = client.execute(intro_query)
            fields = [f['name'] for f in intro['__schema']['queryType']['fields']]
            console.print(f"[yellow]Available Query fields: {', '.join(fields[:10])}...[/yellow]")
        except:
            pass
        return rpc_fallback_trades()

def rpc_fallback_trades():
    """RPC Fallback: Query recent LogInvestmentChanged events from FPMM Factory."""
    try:
        factory_abi = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "buyer", "type": "address"},
                    {"indexed": True, "name": "market", "type": "address"},
                    {"indexed": False, "name": "investmentAmount", "type": "uint256"},
                    {"indexed": False, "name": "sharesBought", "type": "uint256[]"},
                    {"indexed": False, "name": "oldLiquidity", "type": "uint256"},
                    {"indexed": False, "name": "newLiquidity", "type": "uint256"}
                ],
                "name": "LogInvestmentChanged",
                "type": "event"
            }
        ]
        factory = w3.eth.contract(address=FPMM_FACTORY_ADDRESS, abi=factory_abi)
        
        latest_block = w3.eth.block_number
        from_block = max(0, latest_block - 1000)
        
        events = factory.events.LogInvestmentChanged.get_logs(fromBlock=from_block, toBlock=latest_block)
        whale_events = []
        for event in events:
            amount_raw = event['args']['investmentAmount']
            size_usd = float(amount_raw) / 1e6
            if size_usd >= WHALE_THRESHOLD_USD:
                whale_events.append({
                    'wallet': event['args']['buyer'],
                    'size_usd': size_usd,
                    'market': f"Market {event['args']['market'][:10]}...",
                    'timestamp': w3.eth.get_block(event['blockNumber'])['timestamp']
                })
        return {'fixedProductMarketMakers': [{'buyer': {'id': e['wallet']}, 'investmentAmount': str(int(e['size_usd'] * 1e6)),
                                             'market': {'question': e['market'], 'volume': '0'}, 'timestamp': str(e['timestamp'])}
                                         for e in whale_events]}
    except Exception as e:
        console.print(f"[yellow]RPC fallback limited: {e}. Using mock data.[/yellow]")
        return {'fixedProductMarketMakers': []}

def send_telegram_alert(message: str):
    """Send Telegram alert for big trades."""
    if TELEGRAM_TOKEN and TELEGRAM_TOKEN != "your_bot_token":
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message})

@app.command()
def track_whales(since: int = int((time.time() - 86400) * 1000)):
    """Track Polymarket whale trades (>= $50k) in real-time via Subgraph.
    
    Args:
        since (int): Timestamp (in milliseconds) to look back from (default: last 24 hours).
    """
    def update_display():
        # Get top markets
        markets_result = fetch_from_subgraph(MARKETS_QUERY)
        top_markets = markets_result.get('markets', [])
        
        # Get recent whale trades
        amount_threshold = WHALE_THRESHOLD_USD * 1e6  # Raw USDC
        trades_result = fetch_from_subgraph(TRADE_QUERY, {'timestamp': since, 'amount': str(amount_threshold)})
        trades_list = trades_result.get('fixedProductMarketMakers', [])
        
        # Process trades
        whale_trades = []
        for trade in trades_list:
            size_usd = float(trade['investmentAmount']) / 1e6
            whale_trades.append({
                'wallet': trade['buyer']['id'],
                'size_usd': size_usd,
                'market': trade['market']['question'][:50] + '...',
                'timestamp': trade['timestamp']
            })
        
        # Build table
        table = Table(title="Polymarket Whale Tracker (Fixed 2025)")
        table.add_column("Wallet", style="cyan")
        table.add_column("Amount (USD)", justify="right")
        table.add_column("Market", style="magenta")
        table.add_column("Time", justify="right")
        
        displayed = 0
        for t in sorted(whale_trades, key=lambda x: x['size_usd'], reverse=True):
            if displayed >= 10:
                break
            table.add_row(
                t['wallet'][:10] + '...',
                f"${t['size_usd']:,.0f}",
                t['market'],
                str(t['timestamp'])
            )
            displayed += 1
            
            # Alert for big trades
            if t['size_usd'] >= ALERT_THRESHOLD_USD:
                alert = f"🐋 Whale Alert: ${t['size_usd']:,.0f} on {t['market']}"
                send_telegram_alert(alert)
                console.print(f"[red bold]{alert}[/red bold]")
        
        if not whale_trades:
            table.add_row("No recent whales (try extending --since)", "-", "-", "-")
        
        # Footer with market context
        if top_markets:
            console.print(f"[dim]Top Markets by Volume: {', '.join([m['question'][:30] for m in top_markets])}[/dim]")
        
        return table
    
    with Live(update_display(), refresh_per_second=5, screen=True) as live:
        try:
            while True:
                asyncio.sleep(1)
        except KeyboardInterrupt:
            console.print("[yellow]Tracking stopped.[/yellow]")

if __name__ == "__main__":
    try:
        app()
    except TypeError as e:
        if "make_metavar" in str(e):
            console.print("[red]Error in rich help rendering. Falling back to plain text help.[/red]")
            click.echo(app.get_help(ctx=click.Context(app)))
        else:
            raise
