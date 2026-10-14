"""tm.machine: the manifest describes the llama-server binary the research router's plist starts."""

from pathlib import Path

from tm.machine import LLAMA_SERVER_FALLBACK, llama_server_default, llama_server_in

PLIST = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.pail.llama-research</string>
  <key>ProgramArguments</key><array>
    <string>/opt/llama/build-b11612/bin/llama-server</string>
    <string>--port</string><string>8081</string>
  </array>
</dict></plist>
"""


def test_the_binary_is_the_plists_first_argument(tmp_path: Path) -> None:
    assert llama_server_in(PLIST) == Path("/opt/llama/build-b11612/bin/llama-server")
    assert llama_server_in(b"not a plist") is None
    assert llama_server_in(PLIST.replace(b"llama-server</string>", b"other</string>", 1)) is None
    plist = tmp_path / "research.plist"
    plist.write_bytes(PLIST)
    assert llama_server_default(plist) == Path("/opt/llama/build-b11612/bin/llama-server")
    assert llama_server_default(tmp_path / "missing.plist") == Path(LLAMA_SERVER_FALLBACK).expanduser()
