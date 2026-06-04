import time
import httpx
import sys
from rich.live import Live
from rich.table import Table
from rich.console import Console

console = Console()
store_id = sys.argv[1] if len(sys.argv) > 1 else "ST1008"

def generate_table() -> Table:
    table = Table(title=f"Live Store Intelligence Dashboard - {store_id}")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    try:
        res = httpx.get(f"http://localhost:8000/stores/{store_id}/metrics")
        if res.status_code == 200:
            data = res.json()
            table.add_row("Unique Visitors", str(data.get("unique_visitors", 0)))
            table.add_row("Conversion Rate", f"{data.get('conversion_rate', 0):.2%}")
            table.add_row("Abandonment Rate", f"{data.get('abandonment_rate', 0):.2%}")
            table.add_row("Queue Depth", str(data.get("queue_depth", 0)))
        else:
            table.add_row("API Status", f"Error {res.status_code}")
    except Exception as e:
        table.add_row("API Status", "Offline or Unreachable")

    try:
        ano = httpx.get(f"http://localhost:8000/stores/{store_id}/anomalies")
        if ano.status_code == 200:
            data = ano.json()
            anomalies = data.get("anomalies", [])
            if anomalies:
                table.add_row("Active Anomalies", str(len(anomalies)), style="red")
            else:
                table.add_row("Active Anomalies", "0", style="green")
    except:
        pass

    return table

def main():
    try:
        with Live(generate_table(), refresh_per_second=2) as live:
            while True:
                time.sleep(1)
                live.update(generate_table())
    except KeyboardInterrupt:
        console.print("\n[bold green]Dashboard closed.[/bold green]")

if __name__ == "__main__":
    main()
