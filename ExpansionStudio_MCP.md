# ExpansionStudio MCP Server

ExpansionStudio includes a local stdio MCP server for ChatGPT Desktop, Codex, and other MCP clients.

The MCP server is intentionally thin. It does not rewrite project files itself. Each tool calls the existing CLI:

```powershell
python -m expansionstudio ...
```

The CLI stdout JSON is parsed and returned as the MCP tool response.

## Files

- Server: `expansionstudio/mcp_server.py`
- CLI entrypoint: `python -m expansionstudio`
- MCP entrypoint: `python -m expansionstudio.mcp_server`

## Start Locally

From the ExpansionStudio repository root:

```powershell
python -m expansionstudio.mcp_server --root "C:\Users\Ehero\Desktop\decomps\pokeemerald-expansion"
```

You can also set the target project root with an environment variable:

```powershell
$env:EXPANSIONSTUDIO_ROOT = "C:\Users\Ehero\Desktop\decomps\pokeemerald-expansion"
python -m expansionstudio.mcp_server
```

The server communicates over stdio and waits for MCP JSON-RPC messages from the client.

## ChatGPT Desktop / MCP Client Example

Use this as a client configuration example. Adjust the Python path and project path for your machine.

```json
{
  "mcpServers": {
    "expansionstudio": {
      "command": "python",
      "args": [
        "-m",
        "expansionstudio.mcp_server",
        "--root",
        "C:\\Users\\Ehero\\Desktop\\decomps\\pokeemerald-expansion"
      ],
      "cwd": "C:\\Users\\Ehero\\Desktop\\expansionstudio\\ExpansionStudio"
    }
  }
}
```

If your MCP client does not inherit PATH, use the full Python executable path.

Restart the MCP client after changing its configuration.

## Exposed Tools

Read-only tools:

- `validate_project`
- `doctor`
- `scan_texts`
- `scan_map_events`
- `search_map_scripts`
- `scan_frontier`
- `export_frontier_pool`
- `validate_mon`

Write-capable tools:

- `update_text`
- `update_map_text`
- `update_map_script`
- `add_map_text`
- `add_map_script`
- `add_map_script_with_text`
- `rename_map_script`
- `import_frontier_pool`
- `import_monpool`
- `build`

Write-capable tools require `confirm: true`, unless they support dry-run and are running with `dry_run: true`.

For `import_frontier_pool`, `import_monpool`, and `build`, MCP defaults to `dry_run: true`.
To actually write or run make, pass both:

```json
{
  "dry_run": false,
  "confirm": true
}
```

## Safety Rules

- The project root is fixed when the MCP server starts.
- Tool arguments cannot override `root`, `input_json`, or `pretty`.
- `file` and `source` arguments must be project-relative paths.
- Absolute paths and `..` traversal are rejected.
- `map` is treated as a `data/maps` folder name, not a path.
- MCP never creates Git commits, pushes, or PRs.
- Source write backups are created by the CLI before writing.
- The MCP server returns JSON errors instead of crashing where possible.

## Quick Checks

Check the CLI directly:

```powershell
python -m expansionstudio validate-project --root "C:\Users\Ehero\Desktop\decomps\pokeemerald-expansion" --pretty
python -m expansionstudio scan-texts --root "C:\Users\Ehero\Desktop\decomps\pokeemerald-expansion" --query CONTINUE --pretty
python -m expansionstudio search-map-scripts --root "C:\Users\Ehero\Desktop\decomps\pokeemerald-expansion" --map AbandonedShip_CaptainsOffice --query Cactus --pretty
```

Check that the MCP module compiles:

```powershell
python -m py_compile expansionstudio\mcp_server.py
```

Framed JSON-RPC smoke test:

```powershell
python -c "import json,subprocess,sys; msgs=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'validate_project','arguments':{}}}]; payload=b''.join(b'Content-Length: '+str(len(json.dumps(m).encode())).encode()+b'\r\n\r\n'+json.dumps(m).encode() for m in msgs); p=subprocess.run([sys.executable,'-m','expansionstudio.mcp_server','--root',r'C:\Users\Ehero\Desktop\decomps\pokeemerald-expansion'],input=payload,capture_output=True); print(p.stdout.decode('utf-8','replace')); print(p.stderr.decode('utf-8','replace'),file=sys.stderr); raise SystemExit(p.returncode)"
```

The response is framed with `Content-Length` because stdio MCP uses framed JSON-RPC.