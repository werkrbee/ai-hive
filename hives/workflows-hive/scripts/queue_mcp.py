#!/usr/bin/env python3
"""An MCP server for the review queue, over stdio: the same reads as review_queue.py, and
answers that only the person can give.

Its tools list the queue and show an item, and each open item is also a resource. An MCP
tool is something a model can call, so the answering tool, answer_item, takes no decision
from its arguments, only the item's ID. It asks the person through an MCP elicitation,
which the client shows to its user, and records only their reply, with via "mcp". A client
that doesn't offer elicitation gets the queue read-only: answer_item isn't listed.

The answer is recorded under WORKFLOWS_HIVE_ACTOR, set in the server's environment by
whoever configures it for their client. Like the command, it refuses to answer from inside
an engine run. A client that fills in elicitations without showing them to a person defeats
the point, so configure it only in a client that asks you.

Standard library only. Messages are JSON-RPC 2.0, one per line (the MCP stdio transport).

Usage (in an MCP client's server configuration):
  python3 hives/workflows-hive/scripts/queue_mcp.py [--state-dir DIR] [--queue-dir DIR]
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as engine  # noqa: E402

VERSIONS = ("2025-11-25", "2025-06-18")  # MCP revisions with elicitation, newest first
NAME = "workflows-hive-queue"
URI = "queue://items/"
ID = {"type": "string", "description": "The item's ID (sha256:...), or its first 8 or more hex digits"}
TOOLS = {
    "list_items": {"description": "List the review queue's items: open ones, or every one with all.",
                   "inputSchema": {"type": "object", "properties": {"all": {"type": "boolean"}}}},
    "show_item": {"description": "Show one review queue item and everything it presents.",
                  "inputSchema": {"type": "object", "properties": {"id": ID}, "required": ["id"]}},
    "answer_item": {"description": ("Ask the person to answer one review queue item. The decision is "
                                    "theirs: it comes from their reply to the elicitation this sends, "
                                    "never from this tool's arguments."),
                    "inputSchema": {"type": "object", "properties": {"id": ID}, "required": ["id"]}},
}


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Server:
    def __init__(self, e, stdin=sys.stdin, stdout=sys.stdout):
        self.e, self.stdin, self.stdout = e, stdin, stdout
        self.elicits = False
        self.sent = 0

    def send(self, message):
        self.stdout.write(json.dumps(message) + "\n")
        self.stdout.flush()

    def receive(self):
        line = self.stdin.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except ValueError:
            self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not valid JSON"}})
            return {}

    def serve(self):
        while (message := self.receive()) is not None:
            self.handle(message)

    def handle(self, message):
        if not isinstance(message, dict) or "method" not in message:
            return  # a stray response, or a line already refused
        if "id" not in message:
            return  # a notification: nothing to answer
        try:
            result = self.dispatch(message["method"], message.get("params") or {})
            self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        except RpcError as err:
            self.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": err.code, "message": str(err)}})

    def dispatch(self, method, params):
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in VERSIONS else VERSIONS[0]
            offered = (params.get("capabilities") or {}).get("elicitation")
            # An empty elicitation capability means form mode; a client offering only url mode can't answer.
            self.elicits = isinstance(offered, dict) and (not offered or "form" in offered)
            return {"protocolVersion": version, "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": NAME, "version": "1.0.0"}}
        if method == "ping":
            return {}
        if method == "tools/list":
            names = [n for n in TOOLS if n != "answer_item" or self.elicits]
            return {"tools": [{"name": n, **TOOLS[n]} for n in names]}
        if method == "tools/call":
            return self.call(params.get("name"), params.get("arguments") or {})
        if method == "resources/list":
            return {"resources": [{"uri": URI + i["id"][7:], "name": f"{i['kind']} {i['id'][7:19]}",
                                   "mimeType": "application/json"} for i in self.e.items()]}
        if method == "resources/read":
            uri = params.get("uri", "")
            if not uri.startswith(URI):
                raise RpcError(-32002, f"no resource {uri}")
            try:
                item = self.e.item(uri[len(URI):])
            except engine.EngineError as err:
                raise RpcError(-32002, str(err)) from None
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(item, indent=2)}]}
        raise RpcError(-32601, f"no method {method}")

    def call(self, name, args):
        if name not in TOOLS or (name == "answer_item" and not self.elicits):
            raise RpcError(-32602, f"no tool {name}")
        try:
            if name == "list_items":
                result = self.e.items(None if args.get("all") else "open")
            elif name == "show_item":
                result = self.e.item(str(args.get("id", "")))
            else:
                result = self.answer(str(args.get("id", "")))
        except engine.EngineError as err:
            return {"content": [{"type": "text", "text": str(err)}], "isError": True}
        text = result if isinstance(result, str) else json.dumps(result, indent=2)
        return {"content": [{"type": "text", "text": text}]}

    def answer(self, ref):
        engine.answering_here("mcp")
        engine.actor_id(self.e.actor)  # refused before the person is asked, not after
        item = self.e.item(ref)
        if item["status"] != "open":
            raise engine.EngineError(f"item {item['id']} is {item['status']}; only an open item can be answered")
        if item["kind"] == "escalation":
            schema = {"type": "object", "properties": {"answer": {"type": "string", "title": "Your answer"}},
                      "required": ["answer"]}
        else:
            schema = {"type": "object", "required": ["decision"], "properties": {
                "decision": {"type": "string", "title": "Decision", "enum": ["approve", "deny"]},
                "reason": {"type": "string", "title": "Reason (needed to deny)"}}}
        reply = self.elicit(f"The review queue asks you to answer this {item['kind']}:\n\n"
                            f"{json.dumps({k: item[k] for k in ('id', 'source', 'agent', 'present')}, indent=2)}",
                            schema)
        if reply.get("action") != "accept":
            return f"not answered: the person chose {reply.get('action', 'nothing')}"
        content = reply.get("content")
        if not isinstance(content, dict):
            raise engine.EngineError("the reply had no answer")
        if item["kind"] == "escalation":
            decision, text, reason = "answered", content.get("answer"), None
        else:
            decision = {"approve": "approved", "deny": "denied"}.get(content.get("decision")) \
                if isinstance(content.get("decision"), str) else None
            if decision is None:
                raise engine.EngineError("the reply had no decision")
            text, reason = None, content.get("reason")
        result = self.e.answer_item(item["id"], decision, None, reason, text, "mcp")
        return {k: result[k] for k in ("runId", "status", "pending", "result", "error") if k in result} \
            if "runId" in result else result

    def elicit(self, message, schema):
        """Send an elicitation to the client and wait for its reply. A ping meanwhile is
        answered; any other request is refused, since this answers one thing at a time."""
        self.sent += 1
        rid = f"elicit-{self.sent}"
        self.send({"jsonrpc": "2.0", "id": rid, "method": "elicitation/create",
                   "params": {"message": message, "requestedSchema": schema}})
        while (message := self.receive()) is not None:
            if not isinstance(message, dict):
                continue  # not a message; nothing to answer
            if message.get("id") == rid and "method" not in message:
                error, result = message.get("error"), message.get("result")
                if error is not None:
                    raise engine.EngineError(f"the client couldn't ask: "
                                             f"{error.get('message') if isinstance(error, dict) else error}")
                return result if isinstance(result, dict) else {}
            if message.get("method") == "ping" and "id" in message:
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            elif "method" in message and "id" in message:
                self.send({"jsonrpc": "2.0", "id": message["id"],
                           "error": {"code": -32603, "message": "waiting for the person's answer"}})
        raise engine.EngineError("the client went away before the person answered")


def main():
    ap = argparse.ArgumentParser(description="Serve the review queue over MCP (stdio).")
    ap.add_argument("--state-dir", default=str(engine.DEFAULT_STATE_DIR), help="Where run records live")
    ap.add_argument("--queue-dir", help="Where queue items live (default: queue/ beside --state-dir)")
    ap.add_argument("--workflows-dir", default=str(engine.WORKFLOWS_DIR), help="Where plans live")
    ap.add_argument("--contracts-dir", default=str(engine.CONTRACTS_DIR), help="Where execution contracts live")
    ap.add_argument("--audit", metavar="PATH", help="The audit log (default: audit.jsonl beside --state-dir)")
    args = ap.parse_args()
    e = engine.Engine(args.state_dir, args.workflows_dir, args.contracts_dir, audit=args.audit,
                      actor=os.environ.get("WORKFLOWS_HIVE_ACTOR"), queue=args.queue_dir,
                      log=lambda line: print(line, file=sys.stderr))  # stdout carries only messages
    Server(e).serve()


if __name__ == "__main__":
    main()
