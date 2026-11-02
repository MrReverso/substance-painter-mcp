# Substance Painter MCP

Lets Claude drive an open Adobe Substance 3D Painter: bake, build layers, tune materials, look at the result and export. 86 tools. Live-tested on Painter 12.2.0 on macOS.

This is a fork of [elliezu/SubstancePainterMCP](https://github.com/elliezu/SubstancePainterMCP) 1.0.0. See [CHANGELOG.md](CHANGELOG.md) for what changed, and that project's README for the full tool list. It is not affiliated with Adobe.

## Setup

You need Painter on macOS and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/MrReverso/substance-painter-mcp.git
```

```bash
cd substance-painter-mcp
```

```bash
uv venv --python 3.12 .venv
```

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
```

```bash
ln -sfn "$PWD/painter_plugin/painter_bridge.py" ~/Documents/Adobe/"Adobe Substance 3D Painter"/python/startup/painter_bridge.py
```

Restart Painter. Its log then shows `Bridge listening on ...`. No launch flag is needed.

Then add the server to your MCP client. For Claude Code, put this in a `.mcp.json`, using your own paths:

```json
{
  "mcpServers": {
    "substance-painter": {
      "command": "/path/to/substance-painter-mcp/.venv/bin/python",
      "args": ["-m", "substance_painter_mcp"],
      "env": {
        "SP_MCP_TIMEOUT": "300",
        "SP_MCP_EXPORT_ROOTS": "/path/to/exports",
        "SP_MCP_PROJECT_ROOTS": "/path/to/projects",
        "SP_MCP_MESH_ROOTS": "/path/to/meshes"
      }
    }
  }
}
```

## Settings

| Variable | Meaning |
|---|---|
| `SP_MCP_SOCKET` | Bridge socket, default `~/.painter_bridge.sock`. Set it for both Painter and the server. |
| `SP_MCP_TIMEOUT` | Seconds to wait for Painter, default 30. |
| `SP_MCP_ALLOW_EXECUTE_PYTHON` | `1` enables `execute_python`. |
| `SP_MCP_EXPORT_ROOTS` | Folders exports may write to. |
| `SP_MCP_PROJECT_ROOTS` | Folders `.spp` files may be saved in. |
| `SP_MCP_MESH_ROOTS` | Folders project meshes may come from. |
| `SP_MCP_BAKE_MESH_ROOTS` | Folders high-poly and cage meshes may come from. |
| `SP_MCP_RESOURCE_ROOTS` | Folders imported resources may come from. |

Each file feature stays off until its folders are set. Separate several folders with `:`.

## Typical flow

1. `create_project` with the mesh. If its UVs overlap or tile, pass `settings={"auto_unwrap_settings": {"margin_size": 5, "island_orientation": "AlignWith3DMesh"}}`, then `export_mesh` so the game uses the same UVs.
2. `set_baking_mesh_inputs` with `low_as_high=true` if there is no high-poly mesh, then `start_batch_bake`.
3. Build layers with `create_fill_layer`, `insert_smart_material`, `set_layer_mask` and `insert_mask_effect`. Tune them with `set_fill_parameters` and `set_levels`.
4. Check every side with `capture_turntable`, close-ups with its `focus` and `zoom`, and single channels with `capture_channel`.
5. `export_with_profile` with `profile="roblox"`. Check `omitted_files`: Painter reports Success even when it skips a map.

## Where the other ideas came from

All five projects are MIT licensed. Every file was read except lockfiles, licences and image assets.

| Project | Used |
|---|---|
| [elliezu/SubstancePainterMCP](https://github.com/elliezu/SubstancePainterMCP) | The base of this fork |
| [jwang47/substance-painter-mcp](https://github.com/jwang47/substance-painter-mcp) | Its notes on Painter's quirks, tuning generators, content effects, insert positions, Levels values, one undo step per recipe |
| [parodyband/painter-mcp](https://github.com/parodyband/painter-mcp) | Returning captures as images, channel previews, `export_mesh` |
| [dcc-mcp/dcc-mcp-substance3d-painter](https://github.com/dcc-mcp/dcc-mcp-substance3d-painter) | The idea of a camera orbit, with the rotation order corrected for Painter, and the `postfx` crash in `usages()` |
| [cavi-ai/substance-mcp](https://github.com/cavi-ai/substance-mcp) | Reporting the maps Painter skipped |

Read and left out, because they solve problems a one-person setup doesn't have: leases, receipts and brokers for several clients, installers and updaters, and a sandbox for script files.

`QScreen.grabWindow`, the capture used by jwang47 and parodyband, is not used here. On macOS it returns whatever is on screen at that spot, including other apps.

## Limits

- The bridge and capture are macOS-only as written. The bridge also needs a Unix socket.
- `capture_viewport` and `capture_turntable` need Painter to have macOS Screen Recording permission, its window not to be minimized and the display to be awake. `capture_channel` doesn't need any of these.
- Painter's Python API has no brush strokes, so paint layers can't be drawn by script.
- No tool adds a stack channel such as Opacity. Use `execute_python` for that.
- Exported textures and meshes have not been tested in Roblox yet.
