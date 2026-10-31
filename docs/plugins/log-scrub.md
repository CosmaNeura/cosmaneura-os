# Log scrubbing in the CosmaBot connectors plugin

The plugin process uses the same log scrubber as the CosmaBot service. Scrubbing is always on. It does not read the data-mode switch.

Labeled and strongly patterned identifiers are redacted. That includes MRN, date of birth, SSN, phone, email, name, and the other identifier fields the shared scrubber already knows. Clinical note fields are dropped by field name. Query strings in logged URLs are redacted. Operational values such as a request id and an HTTP status stay.

Tool results on the MCP protocol stream are not logs. A successful Elation or Athena read still returns the page the signed-in caller asked for.

Athena tools live in `src/cosmas_os/plugins/athena.py` and do not log chart rows. The same startup install covers that module. `atlas_md.py` is not part of this plugin tree. Any logger it adds later in this process is covered by the same install.

## Paths that are scrubbed

- The root logger, which the server attaches to stderr at startup, and any handler added later. The MCP server logs handler failures on `mcp.server.runner` and a startup debug line on `mcp.server.lowlevel.server`. Both use that process logging.
- httpx request lines. `runtime.py` does not log the call itself. httpx logs the method and URL, query string included, on the `httpx` logger. Those lines go through the same filter.
- Text written straight to stderr. That includes the sign-in message, warnings, and a traceback Python prints if the process fails.
- Text written to stdout while the stdio transport is serving. During that time the transport points stdout at stderr so a stray print cannot land on the protocol stream. Those prints are treated as logs. The protocol frames use a separate descriptor and are left intact.

`plugins/cosmabot-connectors/` has no server of its own. The generated package starts this process, so its stderr is the stream above. The configuration command's JSON result is not a log and is not scrubbed.
