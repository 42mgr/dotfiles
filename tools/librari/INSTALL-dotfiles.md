# librari (vendored)

Snapshot of `tools/librari` from the private `swift/swift-crm` repo
(source commit `958065eb041a`, 2026-09-23).
The kb it validates lives in that repo; this copy exists so the CLI/MCP server
can be installed on any machine from the dotfiles alone.

    uv tool install --force ~/dotfiles/tools/librari     # → ~/.local/bin/librari
    librari --kb <path-to-kb> check

Refresh: `rsync -a --exclude .venv --exclude __pycache__ <checkout>/tools/librari/ ~/dotfiles/tools/librari/`
then bump the commit above.
