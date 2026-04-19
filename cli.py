"""
cli.py — ShopWave Support Resolution Agent CLI

Usage:
    python cli.py                    # Run all 20 tickets with live output
    python cli.py --ticket T001      # Run a single ticket
    python cli.py --list             # List all tickets and their status
    python cli.py --audit            # Show audit log summary
    python cli.py --quiet            # Run all tickets, minimal output
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

THEME = Theme({
    "approve":   "bold green",
    "deny":      "bold red",
    "escalate":  "bold yellow",
    "tool":      "bold cyan",
    "dim":       "dim white",
    "ticket_id": "bold white",
    "q_pass":    "green",
    "q_fail":    "red",
    "q_none":    "dim white",
    "accent":    "bold bright_blue",
    "header":    "bold white",
    "vip":       "bold yellow",
    "premium":   "bold white",
    "standard":  "dim white",
})

import os
import sys

# Windows terminal encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

console = Console(theme=THEME, highlight=False)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent
_DATA_DIR = _ROOT / "data"
_AUDIT_LOG = _ROOT / "audit_log.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tickets() -> list[dict]:
    return json.loads((_DATA_DIR / "tickets.json").read_text())

def _load_customers() -> dict[str, dict]:
    return {c["customer_id"]: c for c in json.loads((_DATA_DIR / "customers.json").read_text())}

def _load_audit() -> dict | None:
    if not _AUDIT_LOG.exists():
        return None
    return json.loads(_AUDIT_LOG.read_text())

def _resolution_style(r: str | None) -> str:
    if r == "APPROVE":  return "approve"
    if r == "DENY":     return "deny"
    if r == "ESCALATE": return "escalate"
    return "dim"

def _tier_style(tier: str) -> str:
    if tier == "vip":     return "vip"
    if tier == "premium": return "premium"
    return "standard"

def _tier_dot(tier: str) -> str:
    if tier == "vip":     return "[vip]●[/vip]"
    if tier == "premium": return "[premium]●[/premium]"
    return "[standard]●[/standard]"

def _short_desc(desc: str, n: int = 80) -> str:
    return desc[:n] + "..." if len(desc) > n else desc

# ---------------------------------------------------------------------------
# Live ticket processor — streams output as agent runs
# ---------------------------------------------------------------------------

class LiveTicketPrinter:
    """Hooks into the agent's trace events and prints them as they happen."""

    def __init__(self, ticket: dict, customer: dict, quiet: bool = False):
        self.ticket = ticket
        self.customer = customer
        self.quiet = quiet
        self.tool_count = 0
        self.start_time = time.time()

    def on_tool_call(self, tool_name: str, result: dict):
        self.tool_count += 1
        if self.quiet:
            return
        error = result.get("error")
        if error:
            console.print(
                f"  [dim]{self.tool_count:2}.[/dim] [tool]{tool_name}[/tool]  "
                f"[red]✗ {error}[/red]"
            )
        else:
            # Show a brief summary of the result
            summary = _result_summary(tool_name, result)
            console.print(
                f"  [dim]{self.tool_count:2}.[/dim] [tool]{tool_name}[/tool]  "
                f"[dim]{summary}[/dim]"
            )

    def on_decision(self, question: str, value: bool):
        if self.quiet:
            return
        icon = "[q_pass]✓[/q_pass]" if value else "[q_fail]✗[/q_fail]"
        label = {
            "Q1": "Order & customer identified",
            "Q2": "Request within policy",
            "Q3": "Confidence threshold met",
        }.get(question, question)
        console.print(f"       {icon} [dim]{label}[/dim]")

    def on_confidence(self, score: float, factors: dict):
        if self.quiet:
            return
        bar_len = 20
        filled = int(score * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        color = "green" if score >= 0.75 else "yellow" if score >= 0.5 else "red"
        console.print(
            f"       [{color}]{bar}[/{color}] [dim]{score:.2f}[/dim]  "
            f"[dim]dc={factors.get('data_completeness',0):.2f} "
            f"rc={factors.get('reason_clarity',0):.2f} "
            f"pc={factors.get('policy_consistency',0):.2f}[/dim]"
        )

    def on_resolution(self, resolution: str, category: str | None, refund_id: str | None, case_id: str | None):
        elapsed = time.time() - self.start_time
        style = _resolution_style(resolution)
        detail = ""
        if refund_id:
            detail = f"  [dim]{refund_id}[/dim]"
        elif case_id:
            detail = f"  [dim]{case_id}[/dim]"
        elif category:
            detail = f"  [dim]{category}[/dim]"

        if self.quiet:
            console.print(
                f"  [{style}]{resolution:8}[/{style}]  "
                f"[ticket_id]{self.ticket['ticket_id']}[/ticket_id]  "
                f"[dim]{self.customer.get('name','?'):12}[/dim]"
                f"{detail}  [dim]{elapsed:.1f}s[/dim]"
            )
        else:
            console.print(
                f"\n  [{style}]▶ {resolution}[/{style}]{detail}  "
                f"[dim]{elapsed:.1f}s · {self.tool_count} tool calls[/dim]"
            )

    def on_reply(self, message: str):
        if self.quiet:
            return
        # Show first 2 lines of the reply
        lines = [l for l in message.strip().split("\n") if l.strip()][:2]
        for line in lines:
            console.print(f"       [dim italic]{line[:90]}[/dim italic]")

    def on_replan(self, trigger: str, path: str):
        if self.quiet:
            return
        console.print(f"       [yellow]↻ replan[/yellow]  [dim]{trigger} → {path}[/dim]")


def _result_summary(tool_name: str, result: dict) -> str:
    """One-line summary of a tool result."""
    if tool_name == "get_order":
        return f"order {result.get('order_id','?')}  {result.get('status','?')}  ${result.get('amount',0):.2f}"
    if tool_name == "get_customer":
        return f"{result.get('name','?')}  [{result.get('tier','?')}]"
    if tool_name == "get_product":
        return f"{result.get('name','?')}  {result.get('return_window_days','?')}d window"
    if tool_name == "search_knowledge_base":
        topics = result.get("matched_topics", [])
        return f"matched: {', '.join(topics[:3]) if topics else 'general'}"
    if tool_name == "check_refund_eligibility":
        elig = result.get("eligible")
        reason = result.get("reason", "")[:60]
        return f"eligible={elig}  {reason}"
    if tool_name == "issue_refund":
        return f"refund_id={result.get('refund_id','?')}  ${result.get('amount',0):.2f}"
    if tool_name == "send_reply":
        return f"delivered={result.get('delivered')}  {result.get('message_preview','')[:40]}"
    if tool_name == "escalate":
        return f"case_id={result.get('case_id','?')}  priority={result.get('priority','?')}"
    return str(result)[:60]


# ---------------------------------------------------------------------------
# SSE-style trace logger that calls the printer
# ---------------------------------------------------------------------------

class CLITraceLogger:
    """Replaces TraceLogger — calls LiveTicketPrinter instead of writing to file."""

    def __init__(self, printer: LiveTicketPrinter):
        self._printer = printer
        self._lock = asyncio.Lock()

    async def emit(self, event_type: str, ticket_id: str, payload: dict) -> None:
        pass

    async def ticket_ingested(self, ticket_id: str, ticket: dict) -> None:
        pass

    async def tool_call_before(self, ticket_id: str, tool_name: str, args: dict) -> None:
        pass

    async def tool_call_after(self, ticket_id: str, tool_name: str, result: dict) -> None:
        async with self._lock:
            self._printer.on_tool_call(tool_name, result)

    async def decision_evaluated(self, ticket_id: str, question: str, value: bool) -> None:
        async with self._lock:
            self._printer.on_decision(question, value)

    async def confidence_computed(self, ticket_id: str, score: float, factors: dict) -> None:
        async with self._lock:
            self._printer.on_confidence(score, factors)

    async def checkpoint_emitted(self, ticket_id: str, checkpoint: dict) -> None:
        pass

    async def resolution_final(self, ticket_id: str, resolution: str, category: str | None = None) -> None:
        pass

    async def replan_triggered(self, ticket_id: str, trigger: str, alternative_path: str) -> None:
        async with self._lock:
            self._printer.on_replan(trigger, alternative_path)

    async def replan_outcome(self, ticket_id: str, outcome: str) -> None:
        pass

    async def session_memory_read(self, ticket_id: str, customer_id: str, records_count: int) -> None:
        pass

    async def session_memory_write(self, ticket_id: str, customer_id: str, resolution: str) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Run a single ticket with live CLI output
# ---------------------------------------------------------------------------

async def run_ticket_cli(ticket: dict, customers: dict, quiet: bool = False) -> dict:
    from agent.graph import build_graph, set_runtime
    from agent.session_memory import SessionMemory
    from agent.state import initial_state

    customer = customers.get(ticket.get("customer_id", ""), {})
    printer = LiveTicketPrinter(ticket, customer, quiet=quiet)
    logger = CLITraceLogger(printer)
    session_memory = SessionMemory()
    results: list = []

    graph = build_graph(demo_mode=True)
    set_runtime(session_memory, logger, results)

    if not quiet:
        tier_dot = _tier_dot(customer.get("tier", "standard"))
        console.print(
            f"\n[ticket_id]{ticket['ticket_id']}[/ticket_id]  "
            f"{tier_dot} [dim]{customer.get('name','?'):12}[/dim]  "
            f"[dim]{ticket.get('issue_type','').replace('_',' ')}[/dim]"
        )
        console.print(f"  [dim italic]{_short_desc(ticket.get('description',''))}[/dim italic]")
        console.print()

    try:
        state = initial_state(ticket)
        config = {"configurable": {"thread_id": ticket["ticket_id"]}}
        final_state = await graph.ainvoke(state, config=config)

        resolution = final_state.get("resolution")
        category = final_state.get("escalation_category")
        refund_id = final_state.get("refund_id")
        case_id = final_state.get("case_id")

        printer.on_resolution(resolution or "UNKNOWN", category, refund_id, case_id)

        # Print reply if not quiet
        if not quiet:
            tool_calls = final_state.get("tool_calls") or []
            for tc in reversed(tool_calls):
                if tc.get("tool_name") == "send_reply":
                    msg = tc.get("input_args", {}).get("message") or \
                          tc.get("output", {}).get("message_preview", "")
                    if msg:
                        printer.on_reply(msg)
                    break

        return {
            "ticket_id": final_state.get("ticket_id", ticket["ticket_id"]),
            "customer_id": ticket.get("customer_id", ""),
            "tool_calls": final_state.get("tool_calls") or [],
            "reasoning": {
                "q1_identified": final_state.get("q1_identified"),
                "q2_in_policy": final_state.get("q2_in_policy"),
                "q3_confident": final_state.get("q3_confident"),
            },
            "confidence_score": final_state.get("confidence_score"),
            "confidence_factors": final_state.get("confidence_factors"),
            "self_reflection_note": final_state.get("self_reflection_note"),
            "replan_attempts": final_state.get("replan_attempts") or [],
            "checkpoint_events": final_state.get("checkpoint_events") or [],
            "resolution": resolution,
            "escalation_category": category,
            "refund_id": refund_id,
            "case_id": case_id,
            "denial_reason": final_state.get("denial_reason"),
            "processing_error": final_state.get("processing_error"),
        }

    except Exception as exc:
        console.print(f"  [red]ERROR: {exc}[/red]")
        return {
            "ticket_id": ticket["ticket_id"],
            "customer_id": ticket.get("customer_id", ""),
            "tool_calls": [], "reasoning": {}, "confidence_score": None,
            "confidence_factors": None, "self_reflection_note": None,
            "replan_attempts": [], "checkpoint_events": [],
            "resolution": None, "escalation_category": None,
            "refund_id": None, "case_id": None, "denial_reason": None,
            "processing_error": str(exc),
        }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list():
    """List all tickets with their current status."""
    tickets = _load_tickets()
    customers = _load_customers()
    audit = _load_audit()

    # Build status map from audit log
    status_map: dict[str, str] = {}
    if audit:
        for r in audit.get("ticket_audit", []):
            res = r.get("resolution")
            if res == "APPROVE":   status_map[r["ticket_id"]] = "resolved"
            elif res == "DENY":    status_map[r["ticket_id"]] = "denied"
            elif res == "ESCALATE":status_map[r["ticket_id"]] = "escalated"
            elif r.get("processing_error"): status_map[r["ticket_id"]] = "error"

    table = Table(
        box=box.ASCII2,
        show_header=True,
        header_style="header",
        border_style="dim",
        pad_edge=False,
    )
    table.add_column("Ticket", style="ticket_id", width=8)
    table.add_column("Customer", width=14)
    table.add_column("Tier", width=9)
    table.add_column("Issue Type", width=22)
    table.add_column("Status", width=12)
    table.add_column("Description", width=55)

    for t in tickets:
        cid = t.get("customer_id", "")
        customer = customers.get(cid, {})
        tier = customer.get("tier", "standard")
        status = status_map.get(t["ticket_id"], "pending")

        status_text = {
            "resolved":  Text("resolved",  style="approve"),
            "denied":    Text("denied",    style="deny"),
            "escalated": Text("escalated", style="escalate"),
            "error":     Text("error",     style="red"),
            "pending":   Text("pending",   style="dim"),
        }.get(status, Text(status, style="dim"))

        table.add_row(
            t["ticket_id"],
            customer.get("name", "?"),
            Text(tier, style=_tier_style(tier)),
            t.get("issue_type", "").replace("_", " "),
            status_text,
            _short_desc(t.get("description", ""), 55),
        )

    console.print()
    console.print(table)
    resolved = sum(1 for s in status_map.values() if s == "resolved")
    escalated = sum(1 for s in status_map.values() if s == "escalated")
    denied = sum(1 for s in status_map.values() if s == "denied")
    pending = len(tickets) - len(status_map)
    console.print(
        f"  [dim]{len(tickets)} tickets  "
        f"[/dim][approve]{resolved} approved[/approve]  "
        f"[escalate]{escalated} escalated[/escalate]  "
        f"[deny]{denied} denied[/deny]  "
        f"[dim]{pending} pending[/dim]\n"
    )


def cmd_audit():
    """Show audit log summary table."""
    audit = _load_audit()
    if not audit:
        console.print("[red]No audit_log.json found. Run the agent first.[/red]")
        return

    records = audit.get("ticket_audit", [])
    customers = _load_customers()

    table = Table(
        box=box.ASCII2,
        show_header=True,
        header_style="header",
        border_style="dim",
        pad_edge=False,
    )
    table.add_column("Ticket", style="ticket_id", width=8)
    table.add_column("Customer", width=12)
    table.add_column("Resolution", width=12)
    table.add_column("Confidence", width=10)
    table.add_column("Tools", width=6)
    table.add_column("Category / Refund", width=28)
    table.add_column("Note", width=45)

    for r in records:
        cid = r.get("customer_id", "")
        customer = customers.get(cid, {})
        res = r.get("resolution") or "ERROR"
        style = _resolution_style(res)
        score = r.get("confidence_score")
        score_str = f"{score:.2f}" if score is not None else "—"
        tools = str(len(r.get("tool_calls", [])))
        detail = r.get("escalation_category") or r.get("refund_id") or r.get("denial_reason", "")
        if detail:
            detail = str(detail)[:28]
        note = (r.get("self_reflection_note") or r.get("processing_error") or "")[:45]

        table.add_row(
            r["ticket_id"],
            customer.get("name", "?"),
            Text(res, style=style),
            score_str,
            tools,
            Text(detail, style="dim"),
            Text(note, style="dim italic"),
        )

    meta = audit.get("execution_metadata", {})
    console.print()
    console.print(table)
    console.print(
        f"  [dim]{meta.get('tickets_processed', len(records))} tickets  "
        f"{meta.get('execution_time_ms', '?')}ms  "
        f"run: {meta.get('run_id', '?')[:30]}[/dim]\n"
    )


async def cmd_run_all(quiet: bool = False):
    """Run all 20 tickets concurrently with live output."""
    tickets = _load_tickets()
    customers = _load_customers()

    console.print()
    console.print(Rule("[accent]ShopWave Support Resolution Agent[/accent]", style="dim"))
    console.print(
        f"  [dim]Processing [/dim][accent]{len(tickets)} tickets[/accent][dim] concurrently[/dim]"
    )
    console.print()

    start = time.time()

    if quiet:
        # Quiet mode: progress bar + one line per ticket
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        )
        task_id = progress.add_task("Processing tickets...", total=len(tickets))

        results = []
        semaphore = asyncio.Semaphore(20)

        async def run_one(ticket):
            async with semaphore:
                result = await run_ticket_cli(ticket, customers, quiet=True)
                results.append(result)
                progress.advance(task_id)
                return result

        with progress:
            await asyncio.gather(*[run_one(t) for t in tickets])

    else:
        # Verbose mode: full output per ticket
        # Run concurrently but print sequentially to avoid interleaving
        # Use a lock per-ticket output section
        print_lock = asyncio.Lock()
        results = []

        async def run_one(ticket):
            result = await run_ticket_cli(ticket, customers, quiet=False)
            results.append(result)
            return result

        await asyncio.gather(*[run_one(t) for t in tickets])

    elapsed = time.time() - start

    # Save audit log
    _save_audit_log(results, elapsed)

    # Summary
    console.print()
    console.print(Rule(style="dim"))
    approved  = sum(1 for r in results if r.get("resolution") == "APPROVE")
    escalated = sum(1 for r in results if r.get("resolution") == "ESCALATE")
    denied    = sum(1 for r in results if r.get("resolution") == "DENY")
    errors    = sum(1 for r in results if r.get("processing_error"))

    summary = Table(box=box.ASCII2, show_header=False, pad_edge=False, border_style="dim")
    summary.add_column(width=18)
    summary.add_column(width=8)
    summary.add_row("Tickets processed", str(len(results)))
    summary.add_row("[approve]Approved[/approve]",  f"[approve]{approved}[/approve]")
    summary.add_row("[escalate]Escalated[/escalate]", f"[escalate]{escalated}[/escalate]")
    summary.add_row("[deny]Denied[/deny]",    f"[deny]{denied}[/deny]")
    if errors:
        summary.add_row("[red]Errors[/red]", f"[red]{errors}[/red]")
    summary.add_row("[dim]Time[/dim]",        f"[dim]{elapsed:.1f}s[/dim]")
    summary.add_row("[dim]Output[/dim]",      "[dim]audit_log.json[/dim]")

    console.print(summary)
    console.print()


async def cmd_run_ticket(ticket_id: str):
    """Run a single ticket with full verbose output."""
    tickets = _load_tickets()
    customers = _load_customers()

    ticket = next((t for t in tickets if t["ticket_id"] == ticket_id), None)
    if not ticket:
        console.print(f"[red]Ticket {ticket_id} not found.[/red]")
        console.print(f"[dim]Available: {', '.join(t['ticket_id'] for t in tickets)}[/dim]")
        sys.exit(1)

    console.print()
    console.print(Rule(f"[accent]{ticket_id}[/accent]", style="dim"))

    result = await run_ticket_cli(ticket, customers, quiet=False)

    # Append to audit log
    audit = _load_audit() or {"execution_metadata": {}, "ticket_audit": []}
    records = audit["ticket_audit"]
    replaced = False
    for i, r in enumerate(records):
        if r.get("ticket_id") == ticket_id:
            records[i] = result
            replaced = True
            break
    if not replaced:
        records.append(result)
    audit["ticket_audit"] = records
    _AUDIT_LOG.write_text(json.dumps(audit, indent=2, default=str))

    console.print()


def _save_audit_log(results: list, elapsed_ms: float):
    existing = _load_audit()
    if existing is None:
        existing = {"execution_metadata": {}, "ticket_audit": []}

    # Replace or append each record
    records = existing.get("ticket_audit", [])
    for result in results:
        tid = result.get("ticket_id")
        replaced = False
        for i, r in enumerate(records):
            if r.get("ticket_id") == tid:
                records[i] = result
                replaced = True
                break
        if not replaced:
            records.append(result)

    existing["ticket_audit"] = records
    existing["execution_metadata"] = {
        "run_id": f"run_{datetime.datetime.utcnow().isoformat()}Z",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "total_tickets": len(results),
        "tickets_processed": len(results),
        "tickets_resolved": sum(1 for r in results if r.get("resolution") in ("APPROVE", "DENY")),
        "tickets_escalated": sum(1 for r in results if r.get("resolution") == "ESCALATE"),
        "tickets_errored": sum(1 for r in results if r.get("processing_error")),
        "execution_time_ms": round(elapsed_ms * 1000, 2),
    }

    _AUDIT_LOG.write_text(json.dumps(existing, indent=2, default=str))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="python cli.py",
        description="ShopWave Support Resolution Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py                    Run all 20 tickets (verbose)
  python cli.py --quiet            Run all 20 tickets (compact output)
  python cli.py --ticket T001      Run a single ticket
  python cli.py --list             List all tickets and their status
  python cli.py --audit            Show audit log summary
        """,
    )
    parser.add_argument("--ticket",  metavar="ID",  help="Run a single ticket by ID (e.g. T001)")
    parser.add_argument("--list",    action="store_true", help="List all tickets with status")
    parser.add_argument("--audit",   action="store_true", help="Show audit log summary")
    parser.add_argument("--quiet",   action="store_true", help="Compact output (one line per ticket)")

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.audit:
        cmd_audit()
    elif args.ticket:
        asyncio.run(cmd_run_ticket(args.ticket))
    else:
        asyncio.run(cmd_run_all(quiet=args.quiet))


if __name__ == "__main__":
    main()
