# Putting PrivaSight between an agent and the browser

Two ways, depending on how the agent works. Both are tested (`eval/test_shield.py`, `eval/test_gateway.py`).

## A. Shield mode - protects ANY agent that reads the page

Switch on **Shield mode** in the side panel. The page itself is edited in place:

| What an agent can read | What it gets |
|---|---|
| a screenshot (any tool) | tokens instead of PII text, blacked-out sensitive inputs, blurred faces/video |
| page text / DOM / accessibility tree | tokens such as `[PHONE_1]`; PII in `alt`, `title`, `aria-label`, `placeholder` is tokenised too |
| typing | the agent types a token (`{PASSWORD}`, `[PHONE_1]`); PrivaSight swaps in the real value as it is typed |

Tokens and your secrets live in `chrome.storage.session` (memory only, cleared when the browser closes).
An agent should wait for `document.documentElement.dataset.privasight === "ready"` before reading;
it is set only after the page has been quiet for 300 ms.

**Limits:** an agent that runs its own JavaScript and reads an input's `.value` still gets the real value
(we hide it visually and in screenshots, not from page scripts). Text inside `<canvas>` or CSS background images
is not inspected. Shield mode changes what *you* see too - turn it on while the agent works.

## B. Agent gateway (MCP) - the agent has no direct browser access at all

```
agent --MCP--> server/mcp_server.py --HTTP--> server/gateway.py --WebSocket--> extension --> active tab
```

1. Start the server with a secret: `PRIVASIGHT_AGENT_TOKEN=choose-a-secret python -m uvicorn app:app --host 127.0.0.1 --port 8787`
2. Side panel: tick **Agent gateway**, paste the same token. Put the user's secrets in the vault.
3. Register the MCP server in the agent (Claude Desktop example):
   ```json
   { "mcpServers": { "privasight": {
       "command": "python", "args": ["C:/Users/Jayantth/Downloads/PrivaSight/server/mcp_server.py"],
       "env": { "PRIVASIGHT_URL": "http://127.0.0.1:8787", "PRIVASIGHT_AGENT_TOKEN": "choose-a-secret" } } } }
   ```
4. Give the agent **only** these tools (disable its built-in browser/computer tools):
   `privasight_screen` (sanitised screenshot + tokenised elements) and `privasight_act`.

Every screen passes three checks before the agent sees it: the extension's gate, then the gateway's PII scan.
If either fails the agent gets an error, never the data. The gateway binds to localhost; the token stops other
local programs from using it.

## Which to use?
* Agent you don't control, or already has its own browser tools -> **Shield mode**.
* Agent you can configure (MCP) -> **Gateway**, the stronger guarantee (it can't bypass you).
* Both together is fine.
